"""Error analysis of saved benchmark generations.

For debugging tasks, classifies each failure:
  unchanged  - returned the buggy code (ignoring whitespace) while claiming a fix
  no_code    - no code block in the answer
  wrong_fix  - changed the code, but tests still fail
For HumanEval, counts answers without a code block.

    python benchmarks/analyze_failures.py   -> benchmarks/results/failure_analysis.json
"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_models import MODELS, RESULTS, TASKS, extract_code

squash = lambda s: re.sub(r"\s+", "", s)
CLAIMS_FIX = re.compile(r"\b(fix|fixed|corrected|correct version|here's the|updated)\b", re.I)
tasks = {t["id"]: t for t in json.loads((TASKS / "debug_tasks.json").read_text(encoding="utf-8"))}

report = {}
for m in MODELS:
    path = RESULTS / f"{m.key}.raw.json"
    if not path.exists():
        continue
    raw = json.loads(path.read_text(encoding="utf-8"))
    counts = {"unchanged": 0, "unchanged_and_claims_fix": 0, "no_code": 0, "wrong_fix": 0}
    for d in raw["debug"]:
        if d["passed"]:
            continue
        if "```" not in d["answer"]:
            counts["no_code"] += 1
        elif squash(extract_code(d["answer"])) == squash(tasks[d["task"]]["code"]):
            counts["unchanged"] += 1
            counts["unchanged_and_claims_fix"] += bool(CLAIMS_FIX.search(d["answer"]))
        else:
            counts["wrong_fix"] += 1
    counts["humaneval_no_code_block"] = sum("```" not in h["answer"] for h in raw["humaneval"])
    report[m.key] = counts
    print(f"{m.key:20s} {counts}")
(RESULTS / "failure_analysis.json").write_text(json.dumps(report, indent=2))
