"""Measure the Milestone 2 inference engine end to end for each installed model.

For each model and thread count: total startup time through LlamaServer.start(),
RAM after loading and after answering, time to first streamed text, generation
speed, and total time for a typical tutoring answer.

    python benchmarks/measure_inference.py   -> benchmarks/results/inference_m2.json
"""

import json
import statistics
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from edulite.config import REGISTRY, config_from_env, model_status  # noqa: E402
from edulite.conversation import Conversation  # noqa: E402
from edulite.inference import LlamaServer  # noqa: E402

QUESTIONS = [
    "Explain what a Python variable is using a simple example.",
    "What is the difference between a list and a tuple in Python?",
    "Explain gradient descent simply.",
]
RESULTS = Path(__file__).resolve().parent / "results" / "inference_m2.json"


def measure(key: str, threads: int) -> dict:
    server = LlamaServer(config_from_env(key).with_overrides(threads=threads, port=8781, max_tokens=300))
    started = time.perf_counter()
    server.start()
    startup = time.perf_counter() - started
    proc = psutil.Process(server.pid)
    rss_loaded = proc.memory_info().rss
    first_chunk, speeds, totals = [], [], []
    try:
        for question in QUESTIONS:
            conversation = Conversation()
            conversation.add_user(question)
            t0 = time.perf_counter()
            stream = server.stream_chat(conversation.messages())
            first = None
            for _ in stream:
                first = first or time.perf_counter() - t0
            totals.append(time.perf_counter() - t0)
            first_chunk.append(first)
            if stream.tokens_per_second:
                speeds.append(stream.tokens_per_second)
        info = proc.memory_info()
        peak = getattr(info, "peak_wset", info.rss)
    finally:
        server.close()
    return {
        "model": REGISTRY[key].name, "threads": threads,
        "startup_s": round(startup, 2),
        "ram_after_load_mb": round(rss_loaded / 2**20),
        "peak_ram_mb": round(peak / 2**20),
        "first_text_ms": round(statistics.median(first_chunk) * 1000),
        "gen_tok_s": round(statistics.median(speeds), 1) if speeds else None,
        "answer_s_300_tokens_max": round(statistics.median(totals), 1),
    }


def main() -> None:
    results = []
    for key in REGISTRY:
        if not model_status(REGISTRY[key]).installed:
            print(f"skip {key}: not installed")
            continue
        for threads in (4, 8):
            row = measure(key, threads)
            print(json.dumps(row), flush=True)
            results.append(row)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
