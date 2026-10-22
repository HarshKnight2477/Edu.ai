"""Build Edu.ai's fine-tuning dataset: verified coding and debugging examples.

Source: MBPP (Austin et al., 2021, https://github.com/google-research/google-research/tree/master/mbpp),
licensed CC BY 4.0. Only task ids 1-10 (prompt), 511-600 (validation) and 601-974 (train) are used;
the official MBPP test split (11-510) is never touched, so it stays a clean evaluation set.

Example types (chat format, user -> assistant):
  code   - the task, then the verified reference solution in a code block and one short sentence
  debug  - a correct solution with ONE injected bug (off-by-one, flipped comparison, swapped
           operator, wrong start value, missing return, ...). Kept only if the bugged code really
           fails the tests while the original passes. The symptom is produced by running the code;
           the answer is the correct code plus one sentence naming the exact change. Because the
           injected bug is known, every explanation is accurate by construction.

Pipeline: verify solutions -> generate -> quality filter -> de-duplicate -> leak check against
every evaluation set -> split 80/10/10 by task (variants of a task never cross splits).

    python training/build_dataset.py
Writes training/data/{train,val,test}.jsonl and training/data/data_card.json.
"""

from __future__ import annotations

import ast
import copy
import gzip
import json
import random
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))
from sandbox import run_python  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
TASKS = ROOT / "benchmarks" / "tasks"
SEED = 42
SOURCE_IDS = set(range(1, 11)) | set(range(511, 975))      # prompt + validation + train splits
MAX_MUTANTS_PER_TASK = 3
MAX_CODE_LINES = 40


# ----------------------------------------------------------------- mutations

class Mutation:
    """Applies one specific change to one AST node; remembers what changed."""

    def __init__(self, kind: str, node_index: int):
        self.kind, self.node_index = kind, node_index
        self.before = self.after = None


COMPARE_FLIPS = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
ARITH_SWAPS = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Add, ast.FloorDiv: ast.Div, ast.Div: ast.FloorDiv,
               ast.Mod: ast.FloorDiv}
BOOL_SWAPS = {ast.And: ast.Or, ast.Or: ast.And}


def candidate_sites(tree: ast.AST) -> list[tuple[str, int]]:
    sites = []
    for i, node in enumerate(ast.walk(tree)):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARE_FLIPS:
            sites.append(("compare", i))
        elif isinstance(node, ast.BinOp) and type(node.op) in ARITH_SWAPS:
            sites.append(("arith", i))
        elif isinstance(node, ast.BoolOp) and type(node.op) in BOOL_SWAPS:
            sites.append(("boolean", i))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range"
              and node.args and isinstance(node.args[-1] if len(node.args) > 1 else node.args[0], ast.expr)):
            sites.append(("range", i))
        elif (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
              and isinstance(node.value.value, int) and not isinstance(node.value.value, bool)
              and node.value.value in (0, 1)):
            sites.append(("start_value", i))
        elif isinstance(node, ast.Return) and node.value is not None:
            sites.append(("missing_return", i))
    return sites


def apply_mutation(tree: ast.AST, kind: str, index: int) -> tuple[ast.AST, str, str] | None:
    """Returns (mutated tree, before snippet, after snippet) or None if not applicable."""
    tree = copy.deepcopy(tree)
    node = list(ast.walk(tree))[index]
    before = ast.unparse(node)
    if kind == "compare":
        node.ops[0] = COMPARE_FLIPS[type(node.ops[0])]()
    elif kind == "arith":
        node.op = ARITH_SWAPS[type(node.op)]()
    elif kind == "boolean":
        node.op = BOOL_SWAPS[type(node.op)]()
    elif kind == "range":
        if len(node.args) == 1:   # range(n) -> range(1, n): skips the first item
            node.args = [ast.Constant(1), node.args[0]]
        else:                     # range(a, b) -> range(a, b - 1): misses the last item
            node.args[1] = ast.BinOp(node.args[1], ast.Sub(), ast.Constant(1))
    elif kind == "start_value":
        node.value = ast.Constant(1 - node.value.value)
    elif kind == "missing_return":
        expr = ast.Expr(node.value)
        ast.copy_location(expr, node)
        for parent in ast.walk(tree):
            for field in ("body", "orelse"):
                block = getattr(parent, field, None)
                if isinstance(block, list) and node in block:
                    block[block.index(node)] = expr
                    after = ast.unparse(expr)
                    return ast.fix_missing_locations(tree), before, after
        return None
    after = ast.unparse(node)
    return ast.fix_missing_locations(tree), before, after


def explain(kind: str, before: str, after: str) -> str:
    """One accurate sentence: the bugged code used `after`, the fix restores `before`."""
    if kind == "compare":
        return f"The comparison `{after}` should be `{before}`, so the wrong cases passed the check."
    if kind == "arith":
        return f"The expression `{after}` used the wrong operator; it should be `{before}`, which gives the right result."
    if kind == "boolean":
        return f"The condition `{after}` combined its parts with the wrong operator; it should be `{before}`."
    if kind == "range":
        return f"The loop used `{after}` instead of `{before}`, so it skipped an item it should have included."
    if kind == "start_value":
        return f"The starting value in `{after}` is wrong; it should be `{before}`, otherwise the result is off from the start."
    if kind == "missing_return":
        return f"The function computes `{after}` but never returns it, so the caller gets `None`; it needs `{before}`."
    raise ValueError(kind)


# ------------------------------------------------------------------ helpers

SYMPTOM_PROBE = r"""
import json
{setup}
{code}
results = []
for left_src, right_src in {pairs!r}:
    try:
        got = eval(left_src)
        expected = eval(right_src)
        results.append({{"call": left_src, "got": repr(got), "expected": repr(expected), "ok": got == expected}})
    except Exception as e:
        results.append({{"call": left_src, "error": f"{{type(e).__name__}}: {{e}}"[:120]}})
print("@@" + json.dumps(results))
"""


def assert_pairs(tests: list[str]) -> list[tuple[str, str]]:
    """(call, expected) source pairs for asserts of the form `assert call == expected`."""
    pairs = []
    for test in tests:
        try:
            node = ast.parse(test).body[0]
        except SyntaxError:
            continue
        if (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare) and len(node.test.ops) == 1
                and isinstance(node.test.ops[0], ast.Eq)):
            pairs.append((ast.unparse(node.test.left), ast.unparse(node.test.comparators[0])))
    return pairs


def symptom_for(code: str, task: dict) -> str | None:
    pairs = assert_pairs(task["test_list"])
    if not pairs:
        return None
    result = run_python(SYMPTOM_PROBE.format(setup=task.get("test_setup_code", ""), code=code, pairs=pairs), timeout=10)
    match = re.search(r"@@(\[.*\])", result.output)
    if not match:
        return None
    for r in json.loads(match.group(1)):
        if "error" in r:
            return f"`{r['call']}` raises {r['error']}"
        if not r["ok"]:
            if len(r["got"]) > 120 or len(r["expected"]) > 120:
                return f"`{r['call']}` returns the wrong result"
            return f"`{r['call']}` returns `{r['got']}` but should return `{r['expected']}`"
    return None


def passes(code: str, task: dict) -> bool:
    program = "\n".join([task.get("test_setup_code", ""), code, *task["test_list"]])
    return run_python(program, timeout=10).passed


def function_name(task: dict) -> str | None:
    match = re.search(r"assert\s+(?:not\s+)?\(?\s*(?:set\()?(\w+)\(", task["test_list"][0])
    return match.group(1) if match else None


def task_phrase(text: str) -> str:
    """'Write a python function to find X.' -> 'find X'"""
    phrase = re.sub(r"^\s*write\s+an?\s+(python\s+)?(function|program)\s+(to|that)\s+", "", text.strip(), flags=re.I)
    return phrase.rstrip(". ")


CODE_PROMPTS = [
    "Write a Python function called `{name}` to {phrase}.",
    "Can you write `{name}` in Python? It should {phrase}.",
    "I need a Python function `{name}` that can {phrase}.",
]
DEBUG_PROMPTS = [
    "My function has a bug.\n\n```python\n{code}\n```\n\nProblem: {symptom}. Can you fix it?",
    "Why is this wrong? {symptom}.\n\n```python\n{code}\n```",
    "This code doesn't work: {symptom}.\n\n```python\n{code}\n```\n\nFix the bug. Reply with the corrected function "
    "in one code block, then one sentence explaining the cause.",
    "Please help me debug this. {symptom}.\n\n```python\n{code}\n```",
]


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_]\w+", text.lower()))


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# ---------------------------------------------------------------- pipeline

def build_task_examples(task: dict, rng: random.Random) -> tuple[list[dict], Counter]:
    stats = Counter()
    try:
        tree = ast.parse(task["code"])
    except SyntaxError:
        stats["unparseable_reference"] += 1
        return [], stats
    clean = ast.unparse(tree)
    name = function_name(task)
    if not name or f"def {name}(" not in clean:
        stats["no_function_name"] += 1
        return [], stats
    if len(clean.splitlines()) > MAX_CODE_LINES:
        stats["too_long"] += 1
        return [], stats
    if not passes(clean, task):
        stats["reference_fails_tests"] += 1
        return [], stats

    examples = [{
        "task_id": task["task_id"], "type": "code", "name": name,
        "messages": [
            {"role": "user", "content": rng.choice(CODE_PROMPTS).format(name=name, phrase=task_phrase(task["text"]))},
            {"role": "assistant", "content": f"```python\n{clean}\n```\n\nThis defines `{name}` to {task_phrase(task['text'])}."},
        ],
    }]
    stats["code_examples"] += 1

    sites = candidate_sites(tree)
    rng.shuffle(sites)
    kinds_used: set[str] = set()
    for kind, index in sites:
        if len([e for e in examples if e["type"] == "debug"]) >= MAX_MUTANTS_PER_TASK:
            break
        if kind in kinds_used:
            continue  # variety: one bug of each kind per task
        mutated = apply_mutation(tree, kind, index)
        if mutated is None:
            continue
        mutant_tree, before, after = mutated
        mutant = ast.unparse(mutant_tree)
        if mutant == clean:
            continue
        stats["mutants_tried"] += 1
        if passes(mutant, task):
            stats["mutant_still_passes"] += 1   # not a real bug for these tests: discard
            continue
        symptom = symptom_for(mutant, task)
        if not symptom:
            stats["no_symptom"] += 1
            continue
        kinds_used.add(kind)
        examples.append({
            "task_id": task["task_id"], "type": "debug", "bug": kind, "name": name,
            "messages": [
                {"role": "user", "content": rng.choice(DEBUG_PROMPTS).format(code=mutant, symptom=symptom)},
                {"role": "assistant", "content": f"```python\n{clean}\n```\n\n{explain(kind, before, after)}"},
            ],
        })
        stats["debug_examples"] += 1
    return examples, stats


def evaluation_fingerprints() -> tuple[set[str], list[set[str]]]:
    """Function names and token sets of everything used for evaluation."""
    names, texts = set(), []
    for t in json.loads((TASKS / "debug_tasks.json").read_text(encoding="utf-8")):
        names |= set(re.findall(r"def (\w+)\(", t["code"]))
        texts.append(tokens(t["code"]))
    for file in ("hint_tasks.json", "hint_tasks_extended.json"):
        for t in json.loads((TASKS / file).read_text(encoding="utf-8")):
            names.add(re.search(r"assert\s+(?:not\s+)?(\w+)\(", t["tests"]).group(1))
            texts.append(tokens(t.get("request") or " ".join(m["content"] for m in t["turns"])))
    for file in ("concept_quiz.json", "concept_quiz_2.json"):
        for q in json.loads((TASKS / file).read_text(encoding="utf-8")):
            texts.append(tokens(q["question"] + " " + " ".join(q["options"].values())))
    humaneval = ROOT / "benchmarks" / "data" / "HumanEval.jsonl.gz"
    if humaneval.exists():
        for line in gzip.open(humaneval, "rt", encoding="utf-8"):
            row = json.loads(line)
            names.add(row["entry_point"])
            texts.append(tokens(row["prompt"]))
    return names, texts


def main() -> None:
    rng = random.Random(SEED)
    tasks = [json.loads(l) for l in (DATA / "mbpp.jsonl").read_text(encoding="utf-8").splitlines()]
    pool = [t for t in tasks if t["task_id"] in SOURCE_IDS]
    eval_names, eval_texts = evaluation_fingerprints()

    stats = Counter({"source_tasks": len(pool)})
    leaked = []
    kept_tasks = []
    for task in pool:
        name = function_name(task) or ""
        text = tokens(task["text"] + " " + task["code"])
        if name in eval_names or any(jaccard(text, e) >= 0.6 for e in eval_texts):
            leaked.append({"task_id": task["task_id"], "name": name})
            continue
        kept_tasks.append(task)
    stats["dropped_leak_check"] = len(leaked)

    seeds = [rng.randrange(10**9) for _ in kept_tasks]
    with ThreadPoolExecutor(max_workers=8) as pool_exec:
        results = list(pool_exec.map(lambda args: build_task_examples(args[0], random.Random(args[1])),
                                     zip(kept_tasks, seeds)))
    examples = []
    for task_examples, task_stats in results:
        examples += task_examples
        stats.update(task_stats)

    # De-duplicate: identical normalised conversations, and near-identical debug code within a task.
    seen, unique = set(), []
    for ex in examples:
        key = re.sub(r"\s+", " ", json.dumps(ex["messages"])).lower()
        if key in seen:
            stats["dropped_duplicates"] += 1
            continue
        seen.add(key)
        unique.append(ex)

    # Split by task so a task's variants never appear in two splits.
    task_ids = sorted({ex["task_id"] for ex in unique})
    rng.shuffle(task_ids)
    n = len(task_ids)
    split_of = {tid: ("test" if i < n // 10 else "val" if i < n // 5 else "train") for i, tid in enumerate(task_ids)}
    splits = {"train": [], "val": [], "test": []}
    for ex in unique:
        splits[split_of[ex["task_id"]]].append(ex)

    DATA.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        with open(DATA / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    card = {
        "name": "Edu.ai coding & debugging SFT data",
        "source": "MBPP (Austin et al., 2021), CC BY 4.0, task ids 1-10 and 511-974 only",
        "license": "CC BY 4.0 (derived from MBPP); generated explanations by Edu.ai",
        "seed": SEED,
        "stats": dict(stats),
        "splits": {k: {"examples": len(v), "tasks": len({e['task_id'] for e in v}),
                       "types": dict(Counter(e["type"] for e in v)),
                       "bugs": dict(Counter(e.get("bug") for e in v if e["type"] == "debug"))}
                   for k, v in splits.items()},
        "leak_check_dropped": leaked,
        "verification": "every solution passes its MBPP tests; every injected bug fails them",
    }
    (DATA / "data_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(json.dumps({k: card[k] for k in ("stats", "splits")}, indent=2))


if __name__ == "__main__":
    main()
