"""Strict multiple-choice answer extraction and scoring.

Extraction (which option did the model choose?) is kept separate from scoring
(was it right?). Only unambiguous forms are accepted:

  bare letter            "C", "C.", "(C)", "**C**"
  option label at start  "C. <option text>", "C) <option text>" (an explanation may follow)
  explicit label         "Answer: C", "The answer is C", "Option C", "correct option is (C)"

Anything else, or two different labelled letters, is unparseable: the grader
never guesses from the first capital letter of a sentence such as "A list is…".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHOICES = "ABCD"
_STRIP = re.compile(r"[*_`]")
_BARE = re.compile(r"^\(?([ABCD])\)?[.):]?$")
_LEADING_LABEL = re.compile(r"^\(?([ABCD])\)?[.):](?:\s|$)")
_EXPLICIT = re.compile(
    r"\b(?:the\s+)?(?:correct\s+)?(?:answer|option|choice)\s*(?:is|would be|:|=)?\s*\(?([ABCD])\)?(?![A-Za-z])",
    re.I)


def extract_choice(text: str) -> str | None:
    """The option letter the reply selects, or None if it can't be read unambiguously."""
    cleaned = _STRIP.sub("", text).strip()
    if not cleaned:
        return None
    first_line = cleaned.splitlines()[0].strip()
    if _BARE.match(first_line):
        return _BARE.match(first_line).group(1)
    if _LEADING_LABEL.match(first_line):
        return _LEADING_LABEL.match(first_line).group(1)
    labelled = {m.group(1).upper() for m in _EXPLICIT.finditer(cleaned)}
    labelled &= set(CHOICES)
    if len(labelled) == 1:
        return labelled.pop()
    return None


@dataclass(frozen=True)
class QuizScore:
    correct: int
    incorrect: int
    unparseable: int

    @property
    def total(self) -> int:
        return self.correct + self.incorrect + self.unparseable

    @property
    def accuracy(self) -> float:
        """Headline: correct / all questions (unparseable counts as not correct)."""
        return self.correct / self.total if self.total else 0.0

    @property
    def accuracy_on_parseable(self) -> float:
        parsed = self.correct + self.incorrect
        return self.correct / parsed if parsed else 0.0

    @property
    def coverage(self) -> float:
        return (self.correct + self.incorrect) / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        return {"correct": self.correct, "incorrect": self.incorrect, "unparseable": self.unparseable,
                "total": self.total, "accuracy": round(self.accuracy, 3),
                "accuracy_on_parseable": round(self.accuracy_on_parseable, 3),
                "coverage": round(self.coverage, 3)}


def score_quiz(answers: list[tuple[str, str]]) -> QuizScore:
    """answers: (model reply, expected letter) pairs."""
    correct = incorrect = unparseable = 0
    for reply, expected in answers:
        choice = extract_choice(reply)
        if choice is None:
            unparseable += 1
        elif choice == expected:
            correct += 1
        else:
            incorrect += 1
    return QuizScore(correct, incorrect, unparseable)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion (better than ±1.96·SE for small n)."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))
