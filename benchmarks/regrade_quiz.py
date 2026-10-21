"""Re-score saved quiz answers with the strict grader (no new inference).

    python benchmarks/regrade_quiz.py benchmarks/results/tutoring_v1_default.raw.json
Prints old (first-letter) vs strict scores per configuration and writes
<raw file stem>.regraded.json next to the input.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grading import score_quiz, wilson_interval  # noqa: E402

TASKS = Path(__file__).resolve().parent / "tasks"
OLD_LETTER = re.compile(r"\b([ABCD])\b")


def expected_answers() -> dict[str, str]:
    quiz = (json.loads((TASKS / "concept_quiz.json").read_text(encoding="utf-8"))
            + json.loads((TASKS / "concept_quiz_2.json").read_text(encoding="utf-8")))
    return {q["id"]: q["answer"] for q in quiz}


def regrade(raw_path: Path) -> dict:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    expected = expected_answers()
    out = {}
    for config, log in raw.items():
        rows = log["quiz"]
        old_correct = sum(bool(m := OLD_LETTER.search(r["answer"].strip())) and m.group(1) == expected[r["id"]]
                          for r in rows)
        strict = score_quiz([(r["answer"], expected[r["id"]]) for r in rows])
        low, high = wilson_interval(strict.correct, strict.total)
        out[config] = {"old_first_letter_accuracy": round(old_correct / len(rows), 3), **strict.to_dict(),
                       "accuracy_95ci": [round(low, 3), round(high, 3)]}
    return out


def main() -> None:
    for name in sys.argv[1:]:
        path = Path(name)
        result = regrade(path)
        (path.parent / (path.name.replace(".raw.json", ".regraded.json"))).write_text(
            json.dumps(result, indent=2), encoding="utf-8")
        print(f"== {path.name}")
        for config, r in result.items():
            print(f"  {config:12s} old {r['old_first_letter_accuracy']:.1%}  strict {r['accuracy']:.1%} "
                  f"(correct {r['correct']}, wrong {r['incorrect']}, unparseable {r['unparseable']}, "
                  f"coverage {r['coverage']:.0%}, 95% CI {r['accuracy_95ci'][0]:.0%}-{r['accuracy_95ci'][1]:.0%})")


if __name__ == "__main__":
    main()
