"""Generation and prompt speed with vs without weight repacking (lean memory settings).

    python benchmarks/repack_speed.py  -> benchmarks/results/repack_speed.json
"""
import json, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_models import MODELS, MODELS_DIR, RESULTS, Server

LEAN = ["--cache-ram", "0", "--ctx-checkpoints", "1"]
PROMPT = ("Explain, step by step and with a short Python example, how binary search works, why it needs a "
          "sorted list, and what its time complexity is. " * 3)
out = {}
for m in MODELS:
    out[m.key] = {}
    for name, extra in {"repack": LEAN, "no-repack": LEAN + ["--no-repack"]}.items():
        s = Server(MODELS_DIR / m.file, threads=4, ctx=4096, port=8093); s.cmd += extra
        try:
            s.start()
            gen, pp = [], []
            for i in range(3):
                _, t = s.chat([{"role": "user", "content": f"[{i}] " + PROMPT}], 128, m.thinking)
                gen.append(t["predicted_per_second"]); pp.append(t["prompt_per_second"])
            out[m.key][name] = {"gen_tok_s": round(statistics.median(gen), 1), "prompt_tok_s": round(statistics.median(pp), 1)}
        finally:
            s.stop()
        print(m.key, name, out[m.key][name], flush=True)
(RESULTS / "repack_speed.json").write_text(json.dumps(out, indent=2))
