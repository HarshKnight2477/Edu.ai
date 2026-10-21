"""Benchmark candidate small language models on CPU for Edu.ai.

For each GGUF model this starts llama.cpp's ``llama-server`` (CPU only, a fixed
thread count to approximate a modest laptop) and measures:

* startup time (process start -> model loaded)
* RAM: working set after loading, and peak working set over the whole run
* speed: prompt processing and generation tokens/second (llama-server timings)
* coding: pass@1 on a fixed 40-problem subset of HumanEval (greedy decoding)
* debugging: share of 12 buggy beginner functions fixed (judged by unit tests)
* concepts: accuracy on a 30-question programming / CS / AI quiz

Usage:
    python benchmarks/bench_models.py                 # all models in MODELS
    python benchmarks/bench_models.py --only qwen3-1.7b --threads 4

Results go to benchmarks/results/<model>.json plus raw generations for error
analysis, and a combined benchmarks/results/summary.md.
"""

from __future__ import annotations

import argparse
import gzip
import json
import platform
import random
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import run_python  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "runtime" / "llama-cpu" / "llama-server.exe"
MODELS_DIR = ROOT / "models"
TASKS = Path(__file__).resolve().parent / "tasks"
RESULTS = Path(__file__).resolve().parent / "results"
HUMANEVAL = Path(__file__).resolve().parent / "data" / "HumanEval.jsonl.gz"

HUMANEVAL_SUBSET = 40
HUMANEVAL_SEED = 0


@dataclass(frozen=True)
class Candidate:
    key: str
    file: str
    params: str
    license: str
    thinking: bool = False  # hybrid-reasoning model: thinking is disabled for tutoring latency


MODELS = [
    Candidate("qwen2.5-coder-0.5b", "qwen2.5-coder-0.5b-instruct-q4_k_m.gguf", "0.5B", "Apache-2.0"),
    Candidate("qwen3.5-0.8b", "Qwen3.5-0.8B-Q4_0.gguf", "0.8B", "Apache-2.0", thinking=True),
    Candidate("qwen2.5-coder-1.5b", "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf", "1.5B", "Apache-2.0"),
    Candidate("qwen3-1.7b", "Qwen3-1.7B-Q4_K_M.gguf", "1.7B", "Apache-2.0", thinking=True),
    Candidate("qwen3.5-2b", "Qwen3.5-2B-Q4_K_M.gguf", "2B", "Apache-2.0", thinking=True),
    Candidate("granite-4.2-3b", "granite-4.2-3b-Q4_K_M.gguf", "3B", "Apache-2.0", thinking=True),
]


# --------------------------------------------------------------------------- server

class Server:
    def __init__(self, model: Path, threads: int, ctx: int, port: int):
        self.cmd = [str(SERVER), "-m", str(model), "-t", str(threads), "-tb", str(threads),
                    "-c", str(ctx), "-np", "1", "--port", str(port), "--host", "127.0.0.1"]
        self.url = f"http://127.0.0.1:{port}"
        self.proc: subprocess.Popen | None = None
        self.peak_rss = 0

    def start(self) -> float:
        started = time.perf_counter()
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while time.perf_counter() - started < 300:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server exited with code {self.proc.returncode}")
            try:
                if httpx.get(f"{self.url}/health", timeout=1).status_code == 200:
                    return time.perf_counter() - started
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise TimeoutError("model did not load within 300 s")

    def rss_mb(self) -> float:
        info = psutil.Process(self.proc.pid).memory_info()
        self.peak_rss = max(self.peak_rss, getattr(info, "peak_wset", info.rss))
        return info.rss / 2**20

    def chat(self, messages: list[dict], max_tokens: int, thinking: bool) -> tuple[str, dict]:
        body = {"messages": messages, "temperature": 0, "max_tokens": max_tokens, "seed": 0}
        if thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        response = httpx.post(f"{self.url}/v1/chat/completions", json=body, timeout=600)
        response.raise_for_status()
        data = response.json()
        self.rss_mb()
        return data["choices"][0]["message"]["content"] or "", data.get("timings", {})

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ---------------------------------------------------------------------- task helpers

CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def extract_code(text: str) -> str:
    blocks = CODE_BLOCK.findall(text)
    return max(blocks, key=len) if blocks else text


def humaneval_subset() -> list[dict]:
    rows = [json.loads(line) for line in gzip.open(HUMANEVAL, "rt", encoding="utf-8")]
    picks = sorted(random.Random(HUMANEVAL_SEED).sample(range(len(rows)), HUMANEVAL_SUBSET))
    return [rows[i] for i in picks]


def humaneval_program(problem: dict, answer: str) -> str:
    code = extract_code(answer)
    if f"def {problem['entry_point']}" not in code:
        code = problem["prompt"] + code  # model returned only the body
    imports = "\n".join(l for l in problem["prompt"].splitlines() if l.startswith(("import ", "from ")))
    return f"{imports}\n{code}\n\n{problem['test']}\n\ncheck({problem['entry_point']})\n"


QUIZ_LETTER = re.compile(r"\b([ABCD])\b")


# ------------------------------------------------------------------------- benchmark

def benchmark(candidate: Candidate, threads: int, ctx: int, port: int) -> dict:
    model_path = MODELS_DIR / candidate.file
    server = Server(model_path, threads, ctx, port)
    record: dict = {"model": candidate.key, "file": candidate.file, "params": candidate.params,
                    "license": candidate.license, "file_size_gb": round(model_path.stat().st_size / 1e9, 2),
                    "threads": threads, "ctx": ctx}
    raw: dict = {"humaneval": [], "debug": [], "quiz": []}
    gen_speeds, prompt_speeds = [], []

    def ask(messages, max_tokens):
        text, timings = server.chat(messages, max_tokens, candidate.thinking)
        if timings.get("predicted_n", 0) >= 16:
            gen_speeds.append(timings["predicted_per_second"])
        if timings.get("prompt_n", 0) >= 32:
            prompt_speeds.append(timings["prompt_per_second"])
        return text

    try:
        record["startup_s"] = round(server.start(), 2)
        time.sleep(1)
        record["rss_after_load_mb"] = round(server.rss_mb())
        run_started = time.perf_counter()

        # Coding: HumanEval subset
        passed = 0
        for problem in humaneval_subset():
            messages = [
                {"role": "system", "content": "You are an expert Python programmer."},
                {"role": "user", "content": "Complete the following Python function. Reply with the complete "
                 "function, including its signature and any imports it needs, in a single ```python code block."
                 f"\n\n```python\n{problem['prompt']}```"},
            ]
            answer = ask(messages, 512)
            result = run_python(humaneval_program(problem, answer), timeout=10)
            passed += result.passed
            raw["humaneval"].append({"task": problem["task_id"], "passed": result.passed, "answer": answer})
        record["humaneval_pass@1"] = round(passed / HUMANEVAL_SUBSET, 3)

        # Debugging
        fixed = 0
        tasks = json.loads((TASKS / "debug_tasks.json").read_text(encoding="utf-8"))
        for task in tasks:
            messages = [
                {"role": "system", "content": "You are a patient programming tutor."},
                {"role": "user", "content": f"My Python function has a bug.\n\n```python\n{task['code']}```\n\n"
                 f"Problem: {task['symptom']}\n\nFix the bug. Reply with the complete corrected function in one "
                 "```python code block, then one sentence explaining what caused the bug."},
            ]
            answer = ask(messages, 512)
            result = run_python(extract_code(answer) + "\n" + task["tests"], timeout=10)
            fixed += result.passed
            raw["debug"].append({"task": task["id"], "passed": result.passed, "answer": answer})
        record["debug_fix_rate"] = round(fixed / len(tasks), 3)

        # Concept quiz
        correct = 0
        quiz = json.loads((TASKS / "concept_quiz.json").read_text(encoding="utf-8"))
        for q in quiz:
            options = "\n".join(f"{k}. {v}" for k, v in q["options"].items())
            messages = [{"role": "user", "content": f"{q['question']}\n{options}\n\n"
                         "Answer with only the letter of the correct option."}]
            answer = ask(messages, 16)
            match = QUIZ_LETTER.search(answer.strip())
            ok = bool(match) and match.group(1) == q["answer"]
            correct += ok
            raw["quiz"].append({"id": q["id"], "correct": ok, "answer": answer})
        record["quiz_accuracy"] = round(correct / len(quiz), 3)

        # A typical tutoring reply, timed end to end
        started = time.perf_counter()
        reply = ask([{"role": "system", "content": "You are a friendly tutor for beginner programmers."},
                     {"role": "user", "content": "What is a Python list? Explain simply with a short example."}], 300)
        record["tutor_reply_s"] = round(time.perf_counter() - started, 2)
        raw["tutor_reply"] = reply

        record["gen_tok_s"] = round(statistics.median(gen_speeds), 1) if gen_speeds else None
        record["prompt_tok_s"] = round(statistics.median(prompt_speeds), 1) if prompt_speeds else None
        record["bench_minutes"] = round((time.perf_counter() - run_started) / 60, 1)
        server.rss_mb()
        record["peak_rss_mb"] = round(server.peak_rss / 2**20)
    finally:
        server.stop()

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{candidate.key}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (RESULTS / f"{candidate.key}.raw.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return record


def write_summary(records: list[dict], threads: int) -> None:
    cpu = platform.processor() or platform.machine()
    lines = [
        "# Candidate model benchmark (CPU only)",
        "",
        f"Run {datetime.now():%Y-%m-%d %H:%M} on {cpu}, {psutil.cpu_count(logical=False)} physical cores, "
        f"{round(psutil.virtual_memory().total / 2**30)} GB RAM. llama.cpp `llama-server` CPU build, "
        f"**{threads} threads**, context 4096, greedy decoding, thinking disabled for hybrid-reasoning models.",
        "",
        f"HumanEval: {HUMANEVAL_SUBSET}-problem subset (seed {HUMANEVAL_SEED}), pass@1. Debug: 12 buggy beginner "
        "functions, fixed = unit tests pass. Quiz: 30 multiple-choice programming/CS/AI questions.",
        "",
        "| Model | Params | Quant file | Size | Peak RAM | Startup | Gen tok/s | Prompt tok/s | HumanEval | Debug | Quiz | Tutor reply |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        lines.append(
            f"| {r['model']} | {r['params']} | `{r['file']}` | {r['file_size_gb']} GB | {r['peak_rss_mb']} MB | "
            f"{r['startup_s']} s | {r['gen_tok_s']} | {r['prompt_tok_s']} | {r['humaneval_pass@1']:.0%} | "
            f"{r['debug_fix_rate']:.0%} | {r['quiz_accuracy']:.0%} | {r['tutor_reply_s']} s |")
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark candidate SLMs on CPU")
    parser.add_argument("--only", nargs="*", help="model keys to run")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--ctx", type=int, default=4096)
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    selected = [m for m in MODELS if not args.only or m.key in args.only]
    records = []
    for candidate in selected:
        if not (MODELS_DIR / candidate.file).exists():
            print(f"skip {candidate.key}: {candidate.file} not downloaded", flush=True)
            continue
        print(f"== {candidate.key}", flush=True)
        record = benchmark(candidate, args.threads, args.ctx, args.port)
        print(json.dumps(record), flush=True)
        records.append(record)

    # Merge with earlier runs so the summary covers every benchmarked model.
    by_key = {json.loads(p.read_text())["model"]: json.loads(p.read_text())
              for p in RESULTS.glob("*.json") if not p.name.endswith(".raw.json")}
    ordered = [by_key[m.key] for m in MODELS if m.key in by_key]
    write_summary(ordered, args.threads)
    print(f"summary: {RESULTS / 'summary.md'}")


if __name__ == "__main__":
    main()
