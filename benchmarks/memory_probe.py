"""Peak RAM per model under different llama-server memory settings.

Sends the same 12 varied prompts (HumanEval tasks + tutoring questions) to each
model and records the peak working set. Compares:
  default   - llama-server defaults (8 GB prompt cache, 32 context checkpoints)
  lean      - --cache-ram 0 --ctx-checkpoints 1   (what Edu.ai will use)
  lean-norp - lean + --no-repack                  (no repacked weight copy)

    python benchmarks/memory_probe.py
"""
import gzip, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_models import HUMANEVAL, MODELS, MODELS_DIR, RESULTS, Server

CONFIGS = {
    "default": [],
    "lean": ["--cache-ram", "0", "--ctx-checkpoints", "1"],
    "lean-norp": ["--cache-ram", "0", "--ctx-checkpoints", "1", "--no-repack"],
}

rows = [json.loads(l) for l in gzip.open(HUMANEVAL, "rt", encoding="utf-8")]
prompts = [f"Complete this function:\n```python\n{rows[i]['prompt']}```" for i in range(0, 80, 10)]
prompts += ["Explain recursion to a beginner with an example.", "What is gradient descent?",
            "Write a Python function that reverses a linked list.", "What is overfitting and how do I avoid it?"]

results = {}
for m in MODELS:
    results[m.key] = {}
    for name, extra in CONFIGS.items():
        server = Server(MODELS_DIR / m.file, threads=4, ctx=4096, port=8092)
        server.cmd += extra
        try:
            server.start(); time.sleep(1)
            after_load = server.rss_mb()
            for p in prompts:
                server.chat([{"role": "user", "content": p}], 128, m.thinking)
            results[m.key][name] = {"after_load_mb": round(after_load), "peak_mb": round(server.peak_rss / 2**20)}
        finally:
            server.stop()
        print(m.key, name, results[m.key][name], flush=True)

(RESULTS / "memory_probe.json").write_text(json.dumps(results, indent=2))
