import ast
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
import build_dataset as bd  # noqa: E402

TASK = {
    "task_id": 999, "text": "Write a python function to find the sum of the first n natural numbers.",
    "code": "def sum_n(n):\n    total = 0\n    for i in range(1, n + 1):\n        total = total + i\n    return total",
    "test_list": ["assert sum_n(3) == 6", "assert sum_n(5) == 15", "assert sum_n(1) == 1"],
    "test_setup_code": "",
}


def test_task_phrase_and_function_name():
    assert bd.task_phrase(TASK["text"]) == "find the sum of the first n natural numbers"
    assert bd.function_name(TASK) == "sum_n"
    assert bd.assert_pairs(TASK["test_list"])[0] == ("sum_n(3)", "6")


def test_every_mutation_changes_the_code_and_is_explained():
    tree = ast.parse(TASK["code"])
    kinds = {kind for kind, _ in bd.candidate_sites(tree)}
    assert {"arith", "range", "start_value", "missing_return"} <= kinds
    for kind, index in bd.candidate_sites(tree):
        mutated, before, after = bd.apply_mutation(tree, kind, index)
        assert ast.unparse(mutated) != ast.unparse(tree) and before != after
        sentence = bd.explain(kind, before, after)
        assert f"`{before}`" in sentence and f"`{after}`" in sentence


def test_original_tree_is_not_modified():
    tree = ast.parse(TASK["code"])
    before = ast.unparse(tree)
    for kind, index in bd.candidate_sites(tree):
        bd.apply_mutation(tree, kind, index)
    assert ast.unparse(tree) == before


def test_examples_are_verified_by_running_the_tests():
    examples, stats = bd.build_task_examples(TASK, random.Random(0))
    assert stats["code_examples"] == 1 and examples[0]["type"] == "code"
    debug = [e for e in examples if e["type"] == "debug"]
    assert debug and len({e["bug"] for e in debug}) == len(debug)  # one bug of each kind
    for ex in debug:
        buggy = ex["messages"][0]["content"].split("```python\n")[1].split("\n```")[0]
        fixed = ex["messages"][1]["content"].split("```python\n")[1].split("\n```")[0]
        assert not bd.passes(buggy, TASK) and bd.passes(fixed, TASK)


def test_broken_reference_solution_is_dropped():
    broken = {**TASK, "code": TASK["code"].replace("n + 1", "n")}
    examples, stats = bd.build_task_examples(broken, random.Random(0))
    assert examples == [] and stats["reference_fails_tests"] == 1


def test_mbpp_test_split_is_never_a_source():
    assert not bd.SOURCE_IDS & set(range(11, 511))
