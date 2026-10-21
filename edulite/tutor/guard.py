"""Hint-mode output check: keeps complete homework solutions out of hint answers.

Prompt instructions alone did not stop the model from presenting a complete
function as a "hint" (milestone-4-issues.md, P3), so in hint mode the answer
is checked as it streams. Prose passes through immediately. A fenced code
block is held back until it closes and then released only if it does not have
the structure of a complete solution:

    defines a function (``def``) AND returns a value AND has 3+ code lines

Such a block is replaced by a short note offering the full solution on request
(asking for it switches to Write-code mode, where nothing is filtered).
Skeletons without a return value, one-line syntax examples and pseudo-code
lists are kept.

Known limits: code written outside fences, or a solution split across several
small blocks, is not caught; the evaluation reports unfenced solutions
separately.
"""

from __future__ import annotations

import re

FENCE = "```"
REPLACEMENT = ("\n*(I've left out a complete solution so you can write it yourself. "
               "If you want to see the full code, ask for the full solution.)*\n")
_DEF = re.compile(r"^\s*def\s+\w+\s*\(", re.M)
_RETURN = re.compile(r"^\s*return\b(?!\s*(#|$))", re.M)   # "return" with a value, not a bare return


def is_complete_solution(code: str) -> bool:
    lines = [line for line in code.splitlines() if line.strip() and not line.strip().startswith("#")]
    return len(lines) >= 3 and bool(_DEF.search(code)) and bool(_RETURN.search(code))


class HintGuard:
    """Feed streamed text in, get text that is safe to show out."""

    def __init__(self):
        self._pending = ""        # text not yet released
        self._in_code = False
        self.removed = 0          # number of solution blocks replaced

    def feed(self, chunk: str) -> str:
        self._pending += chunk
        out = []
        while True:
            if not self._in_code:
                start = self._pending.find(FENCE)
                if start < 0:
                    # Hold back trailing backticks: they may be the start of a fence.
                    keep = len(self._pending) - len(self._pending.rstrip("`"))
                    out.append(self._pending[:len(self._pending) - keep])
                    self._pending = self._pending[len(self._pending) - keep:]
                    break
                out.append(self._pending[:start])
                self._pending = self._pending[start:]
                self._in_code = True
            else:
                # Opening fence line ends at the first newline; look for the closing fence after it.
                newline = self._pending.find("\n")
                if newline < 0:
                    break
                end = self._pending.find(FENCE, newline)
                if end < 0:
                    break
                block = self._pending[:end + len(FENCE)]
                self._pending = self._pending[end + len(FENCE):]
                self._in_code = False
                out.append(self._release(block))
        return "".join(out)

    def finish(self) -> str:
        """Flush at the end of the answer (an unclosed block is judged as it stands)."""
        rest, self._pending = self._pending, ""
        if self._in_code:
            self._in_code = False
            return self._release(rest)
        return rest

    def _release(self, block: str) -> str:
        body = block.split("\n", 1)[1] if "\n" in block else ""
        if body.endswith(FENCE):
            body = body[:-len(FENCE)]
        if is_complete_solution(body):
            self.removed += 1
            return REPLACEMENT
        return block


def guard_text(text: str) -> tuple[str, int]:
    """Apply the hint check to a complete answer. Returns (safe text, blocks removed)."""
    guard = HintGuard()
    safe = guard.feed(text) + guard.finish()
    return safe, guard.removed


# ------------------------------------------------------------ one-sentence requests
#
# The model shortens explanations when asked, but doesn't reliably keep to one
# sentence (milestone-4-issues.md, m4-v4). When the student explicitly asks for
# one sentence, the answer is trimmed deterministically. To cut cleanly the whole
# answer has to be seen first, so it is shown when complete instead of streamed;
# such answers are short by definition.

_ONE_SENTENCE = re.compile(r"\b(one|1|a single|single)[- ]sentence\b", re.I)
_WANTS_CODE = re.compile(r"\bcode\s*block\b|```", re.I)
_FENCED_BLOCK = re.compile(r"```[^\n]*\n.*?```", re.S)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z`(\"'*])")
# Lead-ins that announce the code rather than explain anything ("Here is the corrected code:").
_INTRO = re.compile(r"^\s*(here(?: is|'s)|below is)[^\n.]*:\s*", re.I | re.M)


def wants_one_sentence(message: str) -> bool:
    return bool(_ONE_SENTENCE.search(message))


def first_sentence(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        return ""
    parts = _SENTENCE_END.split(text, maxsplit=1)
    return parts[0].strip()


def trim_to_one_sentence(answer: str, with_code: bool) -> str:
    """With code: the first code block, then one sentence of explanation. Otherwise: the first sentence.

    The explanation sentence is the first one after the block; if the model wrote
    its explanation before the code instead, the first sentence before it is used,
    so the trim never removes the explanation altogether.
    """
    if with_code:
        block = _FENCED_BLOCK.search(answer)
        if block:
            sentence = first_sentence(_FENCED_BLOCK.sub(" ", answer[block.end():]))
            if not sentence:
                sentence = first_sentence(_INTRO.sub("", answer[:block.start()]))
            return block.group(0) + ("\n\n" + sentence if sentence else "")
    return first_sentence(_FENCED_BLOCK.sub(" ", answer)) or answer.strip()


class OneSentenceGuard:
    """Buffers the whole answer, then releases it trimmed to the requested format."""

    def __init__(self, with_code: bool):
        self.with_code = with_code
        self._buffer: list[str] = []
        self.trimmed = False

    def feed(self, chunk: str) -> str:
        self._buffer.append(chunk)
        return ""

    def finish(self) -> str:
        full = "".join(self._buffer)
        result = trim_to_one_sentence(full, self.with_code)
        self.trimmed = result.strip() != full.strip()
        return result


def select_guard(mode: str, student_message: str):
    """The output check that applies to this answer, or None.

    Hint mode always uses the hint guard (withholding a solution matters more
    than length). Otherwise an explicit one-sentence request gets the trim.
    """
    if mode == "hint":
        return HintGuard()
    if wants_one_sentence(student_message):
        return OneSentenceGuard(with_code=bool(_WANTS_CODE.search(student_message)))
    return None


def apply_guard(guard, text: str) -> str:
    """Run a complete answer through a guard (used by the evaluation)."""
    return text if guard is None else guard.feed(text) + guard.finish()
