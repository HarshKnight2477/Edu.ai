import pytest

from edulite.tutor.guard import REPLACEMENT, HintGuard, guard_text, is_complete_solution

SOLUTION = "def largest(nums):\n    m = nums[0]\n    for n in nums:\n        if n > m:\n            m = n\n    return m\n"
ANSWER = ("Key idea: keep track of the biggest value so far.\n\nTry writing this code:\n\n"
          f"```python\n{SOLUTION}```\n\nWhat should m start as?")


def test_complete_solution_shape():
    assert is_complete_solution(SOLUTION)
    assert not is_complete_solution("def largest(nums):\n    # your code here\n    pass\n")        # skeleton
    assert not is_complete_solution("def largest(nums):\n    m = nums[0]\n    return\n")         # bare return
    assert not is_complete_solution("for n in nums:\n    if n > m:\n        m = n\n")             # no function
    assert not is_complete_solution("def f(x):\n    return x\n")                                  # 2 lines


def test_solution_block_is_replaced_and_prose_kept():
    safe, removed = guard_text(ANSWER)
    assert removed == 1 and "return m" not in safe and REPLACEMENT in safe
    assert safe.startswith("Key idea: keep track") and safe.endswith("What should m start as?")


def test_harmless_code_is_kept():
    text = "Use `max()`? No, try a loop:\n```python\nfor n in nums:\n    print(n)\n```\nThen compare."
    assert guard_text(text) == (text, 0)


@pytest.mark.parametrize("size", [1, 2, 3, 7, 50])
def test_streaming_in_any_chunk_size_gives_the_same_result(size):
    guard = HintGuard()
    out = "".join(guard.feed(ANSWER[i:i + size]) for i in range(0, len(ANSWER), size)) + guard.finish()
    assert out == guard_text(ANSWER)[0] and guard.removed == 1


def test_prose_streams_immediately_and_code_is_held_back():
    guard = HintGuard()
    assert guard.feed("Think about a loop. ") == "Think about a loop. "
    assert guard.feed("``") == ""                        # might be a fence: held
    assert guard.feed("`python\ndef f(x):\n") == ""      # inside a block: held
    assert guard.feed("    y = x\n    return y\n```") == REPLACEMENT


def test_unclosed_block_at_end_is_judged():
    safe, removed = guard_text("Here:\n```python\n" + SOLUTION)  # answer cut off before the closing fence
    assert removed == 1 and "return m" not in safe


def test_multiple_blocks_judged_separately():
    text = f"```python\nx = [1, 2]\n```\nand\n```python\n{SOLUTION}```"
    safe, removed = guard_text(text)
    assert removed == 1 and "x = [1, 2]" in safe


# ------------------------------------------------------------ one-sentence trim

from edulite.tutor.guard import (HintGuard as _HintGuard, OneSentenceGuard, first_sentence,  # noqa: E402
                                 select_guard, trim_to_one_sentence, wants_one_sentence)

FIX = "```python\ndef c2f(c):\n    return c * 9 / 5 + 32\n```"


@pytest.mark.parametrize("message, expected", [
    ("Fix it, then one sentence explaining the bug.", True),
    ("Explain recursion in a single sentence", True),
    ("answer in 1 sentence", True),
    ("Explain recursion with an example", False),
    ("Write one function that sorts sentences", False),
])
def test_wants_one_sentence(message, expected):
    assert wants_one_sentence(message) is expected


def test_first_sentence_does_not_split_decimals_or_abbreviations():
    assert first_sentence("Multiply by 1.8 and add 32. Then return it.") == "Multiply by 1.8 and add 32."
    assert first_sentence("Use a loop, e.g. a for loop, to count. Done.") == "Use a loop, e.g. a for loop, to count."
    assert first_sentence("") == ""


def test_trim_with_code_keeps_block_and_first_sentence_after_it():
    answer = f"Here is the fix:\n{FIX}\nThe bug was integer division. It made 9 // 5 equal 1. Use / instead."
    assert trim_to_one_sentence(answer, with_code=True) == f"{FIX}\n\nThe bug was integer division."


def test_trim_without_code():
    assert trim_to_one_sentence("A stack is LIFO. It has push and pop.", with_code=False) == "A stack is LIFO."


def test_one_sentence_guard_buffers_then_releases_trimmed():
    guard = OneSentenceGuard(with_code=True)
    assert guard.feed(FIX) == "" and guard.feed("\nCause one. Cause two.") == ""
    assert guard.finish() == f"{FIX}\n\nCause one." and guard.trimmed


def test_select_guard_priority():
    assert isinstance(select_guard("hint", "give me a hint in one sentence"), _HintGuard)  # hint policy first
    assert isinstance(select_guard("debug", "code block, then one sentence"), OneSentenceGuard)
    assert select_guard("explain", "explain loops") is None


def test_trim_uses_explanation_before_code_when_none_follows():
    # Small models often explain first and put nothing after the code.
    answer = f"The bug is integer division. Use / instead of //.\n\nHere is the corrected code:\n{FIX}"
    assert trim_to_one_sentence(answer, with_code=True) == f"{FIX}\n\nThe bug is integer division."
    assert trim_to_one_sentence(f"Here is the corrected code:\n{FIX}", with_code=True) == FIX  # nothing to keep
