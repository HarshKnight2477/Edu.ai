"""Milestone 4 evaluation: does tutoring (prompts, then course notes) improve answers?

Three configurations on the same model and tasks, greedy decoding (temperature 0):
  baseline     - the Milestone 2/3 system prompt (unchanged, so it stays a valid comparison)
  tutor        - tutor prompt (level, auto mode, homework policy), no notes
  tutor_notes  - tutor prompt + retrieved course notes

Tasks:
  quiz      60 multiple-choice questions (30 from Milestone 1 + 30 held out), strict grading
  debug     12 buggy functions: fixed = unit tests pass; also unchanged-code answers and
            whether the requested format (one code block, then one sentence) was followed
  hint      10 "stuck on homework" requests (original definition): a violation = any code
            block in the answer passes the exercise's hidden tests
  hint_ext  10 extra cases: notes with the exact / a similar solution, concept-only notes,
            explicit requests for the full answer (a solution is then *expected*), and
            second-turn "next hint" requests

    python benchmarks/eval_tutoring.py --model default lite
Results: benchmarks/results/tutoring_<prompt version>_<model>.json (+ .raw.json with every answer)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_models import extract_code  # noqa: E402
from grading import score_quiz, wilson_interval  # noqa: E402
from sandbox import run_python  # noqa: E402

from eduai.config import config_from_env  # noqa: E402
from eduai.conversation import DEFAULT_SYSTEM_PROMPT  # noqa: E402
from eduai.inference import LlamaServer  # noqa: E402
from eduai.tutor.engine import Tutor  # noqa: E402
from eduai.tutor.guard import apply_guard, select_guard  # noqa: E402
from eduai.tutor.prompts import PROMPT_VERSION  # noqa: E402

TASKS = Path(__file__).resolve().parent / "tasks"
RESULTS = Path(__file__).resolve().parent / "results"
CONFIGS = ("baseline", "tutor", "tutor_notes")
MAX_TOKENS = {"quiz": 16, "debug": 512, "hint": 512}
CODE_BLOCKS = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)
squash = lambda s: re.sub(r"\s+", "", s)


def messages_for(config: str, turns: list[dict], tutor: Tutor) -> tuple[list[dict], dict]:
    if config == "baseline":
        return [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}, *turns], {}
    prepared = tutor.prepare(turns, level="beginner", mode="auto", use_notes=config == "tutor_notes")
    return prepared.messages, {"mode": prepared.mode, "sources": prepared.sources}


def follows_debug_format(answer: str) -> bool:
    """Requested: the corrected function in one code block, then one sentence."""
    text = answer.strip()
    if not text.startswith("```") or len(CODE_BLOCKS.findall(text)) != 1:
        return False
    after = text[text.index("```", 3) + 3:].strip()
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", after) if s.strip()]
    return 0 < len(sentences) <= 2 and len(after) <= 400


def solved_by_code(answer: str, tests: str) -> bool:
    return any(run_python(block + "\n" + tests, timeout=10).passed for block in CODE_BLOCKS.findall(answer))


def solved_without_fence(answer: str, function: str, tests: str) -> bool:
    """Diagnostic: a complete solution written as plain text, outside any code block."""
    plain = CODE_BLOCKS.sub("", answer)
    start = plain.find(f"def {function}(")
    if start < 0:
        return False
    lines = []
    for line in plain[start:].splitlines():
        if lines and line.strip() and not line.startswith((" ", "\t")) and not line.startswith("def "):
            break
        lines.append(line)
    return run_python("\n".join(lines) + "\n" + tests, timeout=10).passed


def function_name(tests: str) -> str:
    return re.search(r"assert\s+(?:not\s+)?(\w+)\(", tests).group(1)


def llama_build() -> str:
    binary = config_from_env().server_command[0]
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30)
        return (out.stdout + out.stderr).strip().splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return "unknown"


def evaluate(model_key: str, threads: int, task_set: str = "all", model_file: Path | None = None,
             configs: tuple[str, ...] = CONFIGS, label: str | None = None) -> dict:
    """``model_file`` evaluates another GGUF (e.g. a fine-tune) with the ``model_key`` settings."""
    load = lambda name: json.loads((TASKS / name).read_text(encoding="utf-8"))
    quiz = load("concept_quiz.json") + load("concept_quiz_2.json")
    debug, hints, hints_ext = load("debug_tasks.json"), load("hint_tasks.json"), load("hint_tasks_extended.json")
    tutor = Tutor()
    config = config_from_env(model_key).with_overrides(threads=threads, port=8795)
    if model_file:
        model_file = Path(model_file).resolve()
        config = config.with_overrides(models_dir=model_file.parent, model=replace(
            config.model, file=model_file.name, size_bytes=model_file.stat().st_size))
    label = label or model_key
    server = LlamaServer(config)
    server.start()
    results = {
        "prompt_version": PROMPT_VERSION, "model": label, "model_file": config.model.file,
        "runtime": llama_build(), "threads": threads, "context_tokens": config.context_tokens,
        "decoding": {"temperature": 0, "top_p": config.top_p, "max_tokens": MAX_TOKENS},
        "task_counts": {"quiz": len(quiz), "debug": len(debug), "hint": len(hints), "hint_ext": len(hints_ext)},
        "task_set": task_set, "hint_guard": True,
        "started": datetime.now().isoformat(timespec="seconds"), "configs": {},
    }
    raw = {}
    try:
        for name in configs:
            started = time.perf_counter()
            row, log = {}, {"quiz": [], "debug": [], "hint": [], "hint_ext": []}
            latency = {"quiz": [], "debug": [], "hint": []}

            def ask(turns: list[dict], kind: str):
                messages, info = messages_for(name, turns, tutor)
                t0 = time.perf_counter()
                result = server.chat(messages, max_tokens=MAX_TOKENS[kind], temperature=0)
                latency[kind].append(time.perf_counter() - t0)
                if "mode" in info:  # tutor configurations only; the baseline is left untouched
                    # Same output checks the web app and CLI apply (hint guard / one-sentence trim).
                    guard = select_guard(info["mode"], turns[-1]["content"])
                    result.text = apply_guard(guard, result.text)
                    info["solutions_withheld"] = getattr(guard, "removed", 0)
                    info["trimmed_to_one_sentence"] = getattr(guard, "trimmed", False)
                return result, info

            # Concept quiz (strict grading; unparseable answers are reported, never guessed)
            answers = []
            quiz_run = quiz if task_set == "all" else []
            debug_run = debug if task_set in ("all", "debug") else []
            hints_run = hints if task_set in ("all", "hint") else []
            hints_ext_run = hints_ext if task_set in ("all", "hint") else []
            for q in quiz_run:
                options = "\n".join(f"{k}. {v}" for k, v in q["options"].items())
                text = f"{q['question']}\n{options}\n\nAnswer with only the letter of the correct option."
                result, info = ask([{"role": "user", "content": text}], "quiz")
                answers.append((result.text, q["answer"]))
                log["quiz"].append({"id": q["id"], "answer": result.text, "expected": q["answer"], **info})
            if quiz_run:
                for subset, prefix in (("m1", None), ("held_out", "q2-")):
                    part = [a for a, q in zip(answers, quiz) if (q["id"].startswith("q2-")) == (prefix is not None)]
                    row[f"quiz_{subset}"] = score_quiz(part).to_dict()
                score = score_quiz(answers)
                row["quiz"] = {**score.to_dict(),
                               "accuracy_95ci": [round(x, 3) for x in wilson_interval(score.correct, score.total)]}

            # Debugging
            fixed = unchanged = formatted = truncated = 0
            for task in debug_run:
                text = (f"My Python function has a bug.\n\n```python\n{task['code']}```\n\nProblem: {task['symptom']}\n\n"
                        "Fix the bug. Reply with the complete corrected function in one ```python code block, "
                        "then one sentence explaining what caused the bug.")
                result, info = ask([{"role": "user", "content": text}], "debug")
                code = extract_code(result.text)
                passed = run_python(code + "\n" + task["tests"], timeout=10).passed
                same = "```" in result.text and squash(code) == squash(task["code"])
                fmt = follows_debug_format(result.text)
                fixed += passed
                unchanged += same
                formatted += fmt
                truncated += result.finish_reason == "length"
                log["debug"].append({"id": task["id"], "passed": passed, "unchanged": same, "format_ok": fmt,
                                     "finish_reason": result.finish_reason, "answer": result.text, **info})
            if debug_run:
                row["debug"] = {"fixed": fixed, "total": len(debug), "fix_rate": round(fixed / len(debug), 3),
                            "fix_rate_95ci": [round(x, 3) for x in wilson_interval(fixed, len(debug))],
                                "unchanged_code": unchanged, "format_followed": formatted, "cut_off_at_limit": truncated}

            # Homework policy, original 10 (definition unchanged)
            violations = unfenced = no_code = 0
            for task in hints_run:
                result, info = ask([{"role": "user", "content": task["request"]}], "hint")
                solved = solved_by_code(result.text, task["tests"])
                plain = not solved and solved_without_fence(result.text, function_name(task["tests"]), task["tests"])
                violations += solved
                unfenced += plain
                no_code += not CODE_BLOCKS.findall(result.text)
                log["hint"].append({"id": task["id"], "gave_solution": solved, "solution_without_code_block": plain,
                                    "answer": result.text, **info})
            if hints_run:
                row["hint"] = {"violations": violations, "total": len(hints),
                               "policy_followed": round(1 - violations / len(hints), 3),
                               "solutions_without_code_block": unfenced, "answers_without_code": no_code}

            # Homework policy, extended cases
            by_category: dict[str, dict] = {}
            for task in hints_ext_run:
                result, info = ask(task["turns"], "hint")
                solved = solved_by_code(result.text, task["tests"])
                plain = not solved and solved_without_fence(result.text, function_name(task["tests"]), task["tests"])
                ok = solved if task["expect"] == "solution" else not solved
                cat = by_category.setdefault(task["category"], {"ok": 0, "total": 0, "solutions": 0, "unfenced": 0})
                cat["ok"] += ok
                cat["total"] += 1
                cat["solutions"] += solved
                cat["unfenced"] += plain
                log["hint_ext"].append({"id": task["id"], "category": task["category"], "expect": task["expect"],
                                        "gave_solution": solved, "solution_without_code_block": plain, "ok": ok,
                                        "answer": result.text, **info})
            if hints_ext_run:
                row["hint_ext"] = by_category

            info = psutil.Process(server.pid).memory_info()
            row["resources"] = {
                "minutes": round((time.perf_counter() - started) / 60, 1),
                "median_seconds": {k: round(statistics.median(v), 2) for k, v in latency.items() if v},
                "server_peak_ram_mb": round(getattr(info, "peak_wset", info.rss) / 2**20),
            }
            results["configs"][name] = row
            raw[name] = log
            print(label, name, json.dumps(row), flush=True)
    finally:
        server.close()

    RESULTS.mkdir(parents=True, exist_ok=True)
    stem = f"tutoring_{PROMPT_VERSION}_{label}" + ("" if task_set == "all" else f"_{task_set}")
    (RESULTS / f"{stem}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (RESULTS / f"{stem}.raw.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", nargs="+", default=["default"])
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--tasks", choices=["all", "hint", "debug"], default="all",
                        help="run only the homework-policy sets (hint) or only the debugging set (debug)")
    args = parser.parse_args()
    for key in args.model:
        evaluate(key, args.threads, args.tasks)


if __name__ == "__main__":
    main()
