"""LoRA fine-tune of the lite model (Qwen3.5-0.8B) on the Milestone 5 dataset.

Every example is formatted exactly as the app sends it at run time: the tutor's own system
prompt (beginner level, auto-detected mode, retrieved course notes) via ``Tutor.prepare``,
the Qwen chat template with thinking disabled, and the loss on the answer tokens only.

    .venv-train\\Scripts\\python training/train_lora.py            # train, keep best epoch by val loss
    .venv-train\\Scripts\\python training/train_lora.py --merge    # merge the adapter for GGUF conversion

Needs the base weights in models/hf/Qwen3.5-0.8B (https://huggingface.co/Qwen/Qwen3.5-0.8B, Apache-2.0).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
import time
from pathlib import Path

import torch
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eduai.tutor.engine import Tutor  # noqa: E402

BASE = ROOT / "models" / "hf" / "Qwen3.5-0.8B"
DATA = ROOT / "training" / "data"
RUN = ROOT / "training" / "runs" / "lite-m5"
MERGED = ROOT / "models" / "finetuned" / "eduai-lite-m5"
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
           "in_proj_qkv", "in_proj_z", "out_proj"]   # attention, MLP and linear-attention projections


def load_rows(name: str) -> list[dict]:
    return [json.loads(l) for l in (DATA / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()]


def encode(tokenizer, tutor: Tutor, row: dict, max_len: int) -> dict | None:
    user, answer = row["messages"]
    prepared = tutor.prepare([user], level="beginner")
    prompt = tokenizer.apply_chat_template(prepared.messages, tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(answer["content"] + "<|im_end|>", add_special_tokens=False)["input_ids"]
    ids = prompt_ids + answer_ids
    if len(ids) > max_len:
        return None
    return {"input_ids": ids, "labels": [-100] * len(prompt_ids) + answer_ids}


def batches(examples: list[dict], size: int, shuffle: bool, rng: random.Random):
    order = list(range(len(examples)))
    if shuffle:
        rng.shuffle(order)
    for i in range(0, len(order), size):
        chunk = [examples[j] for j in order[i:i + size]]
        width = max(len(e["input_ids"]) for e in chunk)
        ids = torch.full((len(chunk), width), 0, dtype=torch.long)
        labels = torch.full((len(chunk), width), -100, dtype=torch.long)
        mask = torch.zeros((len(chunk), width), dtype=torch.long)
        for k, e in enumerate(chunk):
            n = len(e["input_ids"])
            ids[k, :n] = torch.tensor(e["input_ids"])
            labels[k, :n] = torch.tensor(e["labels"])
            mask[k, :n] = 1
        yield ids, labels, mask


def answer_loss(model, ids, labels, mask) -> tuple[torch.Tensor, int]:
    """Cross-entropy on answer tokens only. The vocabulary has 248k entries, so logits are
    computed just for the positions that are scored (full logits do not fit in 8 GB)."""
    base = model.get_base_model()
    hidden = base.model(input_ids=ids.cuda(), attention_mask=mask.cuda()).last_hidden_state
    target = labels[:, 1:].cuda()
    keep = target != -100
    logits = base.lm_head(hidden[:, :-1][keep]).float()
    return torch.nn.functional.cross_entropy(logits, target[keep]), int(keep.sum())


@torch.no_grad()
def evaluate(model, examples: list[dict], batch_size: int) -> float:
    model.eval()
    total, tokens = 0.0, 0
    for ids, labels, mask in batches(examples, batch_size, False, random.Random(0)):
        loss, n = answer_loss(model, ids, labels, mask)
        total += loss.item() * n
        tokens += n
    model.train()
    return total / tokens


def train(args) -> None:
    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(BASE)
    tutor = Tutor()
    data = {}
    for split in ("train", "val"):
        encoded = [encode(tokenizer, tutor, r, args.max_len) for r in load_rows(split)]
        data[split] = [e for e in encoded if e]
        print(f"{split}: {len(data[split])} examples ({len(encoded) - len(data[split])} too long, skipped)")

    model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16).cuda()
    present = {name.rsplit(".", 1)[-1] for name, _ in model.named_modules()}
    targets = [t for t in TARGETS if t in present]
    model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05,
                                             target_modules=targets, task_type="CAUSAL_LM"))
    model.print_trainable_parameters()
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()

    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.0)
    steps_per_epoch = math.ceil(len(data["train"]) / (args.batch * args.accum))
    total_steps = steps_per_epoch * args.epochs
    warmup = max(1, total_steps // 20)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda s: min(1.0, (s + 1) / warmup) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / total_steps))))

    log = {"args": vars(args), "targets": targets, "epochs": []}
    base_val = evaluate(model, data["val"], args.batch)
    print(f"val loss before training: {base_val:.4f}")
    log["val_loss_before"] = base_val
    best = math.inf
    RUN.mkdir(parents=True, exist_ok=True)
    model.train()
    start = time.time()
    for epoch in range(1, args.epochs + 1):
        running, seen = 0.0, 0
        for i, (ids, labels, mask) in enumerate(batches(data["train"], args.batch, True, rng), 1):
            loss, _ = answer_loss(model, ids, labels, mask)
            (loss / args.accum).backward()
            running += loss.item()
            seen += 1
            if i % args.accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
        if seen % args.accum:
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
        val = evaluate(model, data["val"], args.batch)
        entry = {"epoch": epoch, "train_loss": running / seen, "val_loss": val, "minutes": (time.time() - start) / 60}
        log["epochs"].append(entry)
        print(json.dumps(entry))
        if val < best:
            best = val
            model.save_pretrained(RUN / "adapter")
            log["best_epoch"] = epoch
    log["peak_gpu_mb"] = torch.cuda.max_memory_allocated() // 2**20
    (RUN / "train_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"best val loss {best:.4f} (epoch {log['best_epoch']}); adapter in {RUN / 'adapter'}")


def merge() -> None:
    model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(model, RUN / "adapter").merge_and_unload()
    MERGED.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(MERGED)
    AutoTokenizer.from_pretrained(BASE).save_pretrained(MERGED)
    for extra in ("chat_template.jinja", "preprocessor_config.json", "video_preprocessor_config.json"):
        if (BASE / extra).exists():
            shutil.copy(BASE / extra, MERGED / extra)
    print(f"merged model saved to {MERGED}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--accum", type=int, default=8)
    parser.add_argument("--max-len", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    merge() if args.merge else train(args)
