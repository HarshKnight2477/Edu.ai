import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))
from grading import extract_choice, score_quiz, wilson_interval  # noqa: E402


@pytest.mark.parametrize("reply, choice", [
    ("C", "C"), ("C.", "C"), ("(C)", "C"), ("**C**", "C"), ("  b  ".upper(), "B"),
    ("A. Stack", "A"), ("A.\n\n**What it means:** a model that memorises…", "A"),
    ("D) The same list is shared between calls", "D"),
    ("Answer: B", "B"), ("The answer is C.", "C"), ("The correct option is (D).", "D"), ("Option A", "A"),
    ("**C**\n\n**Explanation:** The F1 score is the harmonic mean…", "C"),
])
def test_accepts_unambiguous_answers(reply, choice):
    assert extract_choice(reply) == choice


@pytest.mark.parametrize("reply", [
    "A list is mutable, so the answer depends on the operation.",   # sentence starting with "A"
    "I think it could be B or C.",                                    # no explicit label
    "Answer: B. Actually, the answer is C.",                          # two different labelled letters
    "", "   ", "Binary search",
    "The function returns a dictionary.",
])
def test_rejects_ambiguous_answers(reply):
    assert extract_choice(reply) is None


def test_score_counts_unparseable_separately():
    score = score_quiz([("A", "A"), ("B", "A"), ("A list is…", "A"), ("Answer: C", "C")])
    assert (score.correct, score.incorrect, score.unparseable, score.total) == (2, 1, 1, 4)
    assert score.accuracy == 0.5                      # headline counts unparseable as not correct
    assert round(score.accuracy_on_parseable, 3) == 0.667
    assert score.coverage == 0.75


def test_wilson_interval():
    low, high = wilson_interval(48, 60)
    assert 0.68 < low < 0.69 and 0.88 < high < 0.89
