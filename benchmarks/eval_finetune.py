"""Milestone 5 evaluation: is the fine-tuned lite model better than the base lite model?

Both models are converted and quantized the same way (llama.cpp b11780 convert_hf_to_gguf.py,
then llama-quantize Q4_0) and run with the app's real settings: tutor prompt + course notes,
the lite model's runtime flags, greedy decoding. Three test sets, none used in training:

  heldout    the dataset's test split (46 MBPP tasks never seen in training): "write" requests and
             injected-bug "debug" requests, scored by the task's unit tests (+ debug answer format)
  mbpp       the official MBPP test split (task ids 11-510; training used none of them), first N
             tasks, standard MBPP prompt ("Your code should pass this test: ..."), pass@1
  tutoring   the Milestone 4 quiz / debug / homework-policy benchmark (tutor_notes configuration)

    python benchmarks/eval_finetune.py --gguf models/finetuned/base-reconverted-Q4_0.gguf --label lite-base
    python benchmarks/eval_finetune.py --gguf models/finetuned/eduai-lite-m5-Q4_0.gguf --label lite-m5
Results: benchmarks/results/finetune_<label>.json (+ .raw.json with every answer)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_models import extract_code  # noqa: E402
from eval_tutoring import evaluate as evaluate_tutoring, follows_debug_format  # noqa: E402
from grading import wilson_interval  # noqa: E402
from sandbox import run_python  # noqa: E402

from eduai.config import config_from_env  # noqa: E402
from eduai.inference import LlamaServer  # noqa: E402
from eduai.tutor.engine import Tutor  # noqa: E402
from eduai.tutor.guard import apply_guard, select_guard  # noqa: E402

DATA = ROOT / "training" / "data"
RESULTS = Path(__file__).resolve().parent / "results"
MAX_TOKENS = 512


def passes(code: str, task: dict) -> bool:
    program = "\n".join([task.get("test_setup_code", ""), code, *task["test_list"]])
    return run_python(program, timeout=10).passed


def rate(k: int, n: int) -> dict:
    return {"passed": k, "total": n, "rate": round(k / n, 3) if n else None,
            "rate_95ci": [round(x, 3) for x in wilson_interval(k, n)] if n else None}


def run(gguf: Path, label: str, threads: int, mbpp_n: int, skip_tutoring: bool) -> dict:
    mbpp = {t["task_id"]: t for t in map(json.loads, (DATA / "mbpp.jsonl").read_text(encoding="utf-8").splitlines())}
    heldout = [json.loads(l) for l in (DATA / "test.jsonl").read_text(encoding="utf-8").splitlines()]
    official_test = [mbpp[i] for i in range(11, 11 + mbpp_n)]

    gguf = gguf.resolve()
    config = config_from_env("lite").with_overrides(threads=threads, port=8796, models_dir=gguf.parent)
    config = config.with_overrides(model=replace(config.model, file=gguf.name, size_bytes=gguf.stat().st_size))
    tutor = Tutor()
    server = LlamaServer(config)
    server.start()
    raw = {"heldout": [], "mbpp": []}
    started = time.perf_counter()
    try:
        def ask(text: str) -> str:
            prepared = tutor.prepare([{"role": "user", "content": text}], level="beginner")
            answer = server.chat(prepared.messages, max_tokens=MAX_TOKENS, temperature=0).text
            return apply_guard(select_guard(prepared.mode, text), answer)

        counts = {"code": [0, 0], "debug": [0, 0], "debug_format": [0, 0]}
        for row in heldout:
            task = mbpp[row["task_id"]]
            answer = ask(row["messages"][0]["content"])
            ok = passes(extract_code(answer), task)
            counts[row["type"]][0] += ok
            counts[row["type"]][1] += 1
            entry = {"task_id": row["task_id"], "type": row["type"], "bug": row.get("bug"), "passed": ok,
                     "answer": answer}
            if row["type"] == "debug":
                fmt = follows_debug_format(answer)
                counts["debug_format"][0] += fmt
                counts["debug_format"][1] += 1
                entry["format_ok"] = fmt
            raw["heldout"].append(entry)

        solved = 0
        for task in official_test:
            text = f"{task['text']} Your code should pass this test:\n{task['test_list'][0]}"
            answer = ask(text)
            ok = passes(extract_code(answer), task)
            solved += ok
            raw["mbpp"].append({"task_id": task["task_id"], "passed": ok, "answer": answer})
    finally:
        server.close()

    results = {
        "label": label, "model_file": gguf.name, "model_bytes": gguf.stat().st_size, "threads": threads,
        "decoding": {"temperature": 0, "max_tokens": MAX_TOKENS}, "prompt": "tutor + course notes, beginner",
        "heldout": {"write_code": rate(*counts["code"]), "debug_fixed": rate(*counts["debug"]),
                    "debug_format_followed": rate(*counts["debug_format"])},
        "mbpp_test": {"task_ids": f"11-{10 + mbpp_n}", **rate(solved, len(official_test))},
        "minutes": round((time.perf_counter() - started) / 60, 1),
    }
    print(label, json.dumps(results), flush=True)
    if not skip_tutoring:
        results["tutoring"] = evaluate_tutoring("lite", threads, "all", model_file=gguf, configs=("tutor_notes",),
                                                label=label)["configs"]["tutor_notes"]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"finetune_{label}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (RESULTS / f"finetune_{label}.raw.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--gguf", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--mbpp", type=int, default=100, help="number of MBPP test tasks (from id 11)")
    parser.add_argument("--skip-tutoring", action="store_true")
    args = parser.parse_args()
    run(args.gguf, args.label, args.threads, args.mbpp, args.skip_tutoring)


if __name__ == "__main__":
    main()
