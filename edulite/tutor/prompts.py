"""Tutoring prompts: student levels, answer modes and the homework policy.

Prompts are kept short on purpose. With a 4,096-token context window, every
token of instructions is a token less for the conversation and the answer.
"""

from __future__ import annotations

import re

# Recorded with every evaluation run so results can be tied to the exact prompts.
# m4-v1: first Milestone 4 prompts. m4-v2: format priority, code-first debugging,
# analogies only when helpful, hint mode ignores code in notes. m4-v3: same prompts
# as v2, plus the hint-mode output check (edulite/tutor/guard.py). m4-v4: debug
# explanation length made explicit (one or two sentences). m4-v5: same prompts as
# v4, plus the deterministic one-sentence trim (edulite/tutor/guard.py). m4-v6: the
# trim falls back to the explanation written before the code when none follows it.
PROMPT_VERSION = "m4-v6"

LEVELS = {
    "beginner": ("Beginner: use simple words, short sentences and very small examples. Define each technical term "
                 "the first time you use it. Use an analogy only if it makes the idea clearer. Avoid heavy maths."),
    "intermediate": ("Intermediate: assume the basics are known. Include implementation details, common pitfalls, "
                     "trade-offs and time complexity where relevant."),
    "advanced": ("Advanced: be precise and concise. Include the underlying theory, maths, internals and "
                 "performance considerations."),
}

MODES = {
    "explain": ("Explain clearly: what it is and why it matters, with a small example (code if useful). "
                "Answer a simple factual question in a sentence or two. No headings unless the answer is long."),
    "hint": ("The student is working on an exercise and wants to learn. Do NOT give the full solution or "
             "complete code, even if the course notes contain similar code. Give one or two hints or guiding "
             "questions that lead to the next step and name the key idea. If they ask for another hint, make it "
             "a little more specific, still without the complete solution."),
    "debug": ("Debug: first find the real cause by tracing what the code actually does with the failing input, "
              "line by line. Then show the corrected code, the smallest change that fixes it, keeping the "
              "student's approach. Then, in one or two sentences, say what caused the bug and why the fix works "
              "(exactly one sentence if the student asks for one). Never present unchanged code as a fix. If the "
              "code or error message you need is missing, ask for it."),
    "code": ("Write correct, readable code with brief comments. Then explain the key lines, show an example "
             "input with its expected output, and mention edge cases and time complexity if relevant."),
    "quiz": ("Give the student practice: one short exercise or three multiple-choice questions on the topic, "
             "suited to their level. Do not reveal the answers; ask them to reply and offer feedback."),
    "project": ("Guide a small project: prerequisites, objective, step-by-step plan, starter code, expected "
                "output, common errors, and one extension challenge."),
}

MODE_LABELS = {"explain": "Explain", "hint": "Hint", "debug": "Debug", "code": "Write code",
               "quiz": "Quiz me", "project": "Project"}

RULES = (
    "Rules: Be technically correct; if unsure, say so and suggest how to check. Never invent functions, "
    "libraries, facts or results. Never claim you ran or tested code. Put code in fenced blocks with the "
    "language name. Keep answers focused, without filler or repetition. Never make the student feel bad "
    "about a question or a mistake."
)

# Placed right after the persona so it outranks the level and mode instructions.
FORMAT_PRIORITY = (
    "If the student asks for a specific format or length (for example only a letter, or one code block then "
    "one sentence), follow it exactly. It overrides the teaching steps below."
)

PERSONA = "You are EduLite, a patient, encouraging and accurate tutor for programming, computer science and AI."

# ------------------------------------------------------------------ detection

_FULL_SOLUTION = re.compile(
    r"\b(full|complete|whole|entire|final)\s+(solution|answer|code|program)\b|\bjust\s+(give|show)\b|"
    r"\bgive me the (answer|solution|code)\b|\bsolution please\b", re.I)

# Debug mode needs evidence that the student has a concrete problem with *their* code.
# Words like "error", "exception" or "bug" alone are not enough: conceptual questions
# ("Which keyword handles an exception?") and quiz options ("It raises an error") use them too.
_TRACEBACK = re.compile(
    r"Traceback \(most recent call last\)|^\s*File \".+\", line \d+|"   # a pasted traceback
    r"\b[A-Z]\w*(?:Error|Exception|Warning): \S",                       # an error line: "TypeError: can only..."
    re.M)
_OWN_CODE_PROBLEM = re.compile(
    r"\bfix (my|this|the|it)\b|\bdebug (my|this|it)\b|\bfind the bug\b|"
    r"\bwhy (does|do|is|isn'?t|doesn'?t|won'?t|did) (my|this|it)\b|"
    r"\bwhat'?s wrong with (my|this)\b|\bwhat is wrong with (my|this)\b|"
    r"\bmy (code|program|function|script|loop|class|query|output)\b.{0,60}"
    r"\b(error|bug|wrong|crash|fail|doesn'?t|not work|broken|instead|returns?|gives?|prints?|stuck|infinite)",
    re.I | re.S)
_PROBLEM_WORDS = re.compile(
    r"\b(error|bug|wrong|crash|fails?|doesn'?t work|not working|broken|instead of|expected|infinite loop|"
    r"fix|why)\b", re.I)
_HINT = re.compile(
    r"\bhints?\b|\bstuck\b|homework|assignment|exercise|\bhow (do|should) i (start|approach|begin)\b|"
    r"don'?t (tell|give) me the (answer|solution)|without (giving|telling) (me )?the (answer|solution)", re.I)
_EXPLAIN_REQUEST = re.compile(r"^\s*(explain|what is|what are|what does|define|describe)\b|\bexplain (this|the) concept\b",
                              re.I)
_QUIZ = re.compile(r"\bquiz me\b|\btest me\b|practice (question|problem|exercise)s?|\bgive me (some )?(questions|exercises|mcqs?)\b|\bmcqs?\b", re.I)
_PROJECT = re.compile(r"\b(mini[- ]?)?project\b|\bstep[- ]by[- ]step (guide|plan) to build\b", re.I)
_CODE = re.compile(
    r"\b(write|create|implement|generate|code|program|build)\b.{0,40}\b(function|program|class|script|code|algorithm|query)\b|"
    r"\bcode (for|to)\b|\btranslate\b.{0,40}\b(to|into)\s+(python|c\+\+|c|java|sql)\b|\bconvert\b.{0,30}\b(to|into)\s+(python|c\+\+|c|java)\b",
    re.I)
_CODE_BLOCK = re.compile(r"```|^\s{4,}\S|^\s*(def|class|for|while|if|import|print)\b.*[:)]\s*$", re.M)


def is_debug_request(message: str) -> bool:
    """True when the student shows a concrete problem: a traceback or error line, their code
    together with a problem, or an explicit request to fix or diagnose their own code."""
    if _TRACEBACK.search(message) or _OWN_CODE_PROBLEM.search(message):
        return True
    has_code = bool(_CODE_BLOCK.search(message))
    return has_code and bool(_PROBLEM_WORDS.search(_CODE_BLOCK_TEXT.sub(" ", message)))


# Fenced code is ignored when looking for problem words, so `except ValueError:` inside
# a snippet the student only wants explained doesn't count as a reported problem.
_CODE_BLOCK_TEXT = re.compile(r"```.*?(```|$)", re.S)


def detect_mode(message: str) -> str:
    """Pick an answer mode from the student's message (used when the mode is 'auto').

    Explicit intent wins over keywords: asking for a hint, a quiz or a complete
    solution is honoured first; debugging needs concrete evidence; anything else
    that asks to understand something is Explain.
    """
    if _QUIZ.search(message):
        return "quiz"
    wants_solution = bool(_FULL_SOLUTION.search(message))
    if _HINT.search(message):
        return "code" if wants_solution else "hint"
    if is_debug_request(message):
        return "debug"
    if _EXPLAIN_REQUEST.search(message):
        return "explain"
    if _PROJECT.search(message):
        return "project"
    if _CODE.search(message) or wants_solution:
        return "code"
    return "explain"


# --------------------------------------------------------------------- prompt

_FENCED = re.compile(r"```[^\n]*\n(.*?)```", re.S)
HINT_PLACEHOLDER = "(code example left out in hint mode)"


def redact_worked_solutions(text: str) -> str:
    """For hint mode: drop code examples from a note that could hand over a solution.

    The notes have no metadata separating worked solutions from concepts, so a
    structural rule is used: any fenced block that defines a function or class,
    or is 3+ lines long, is replaced by a placeholder. Prose, inline code and
    one- or two-line snippets (syntax illustrations) are kept.
    """
    def replace(match: re.Match) -> str:
        code = match.group(1)
        lines = [line for line in code.splitlines() if line.strip()]
        if len(lines) >= 3 or re.search(r"^\s*(def|class)\s", code, re.M):
            return HINT_PLACEHOLDER
        return match.group(0)
    return _FENCED.sub(replace, text)


def build_system_prompt(level: str, mode: str, notes: list[tuple[str, str]] | None = None) -> str:
    """notes: (title, text) passages from the course notes, already chosen by retrieval."""
    parts = [PERSONA, FORMAT_PRIORITY, f"Student level: {LEVELS[level]}", f"Task: {MODES[mode]}", RULES]
    if notes:
        if mode == "hint":
            notes = [(title, redact_worked_solutions(text)) for title, text in notes]
            intro = ("Course notes for explaining the ideas involved (written for EduLite and checked for "
                     "accuracy). Use them to explain concepts and suggest the next step, not to write the "
                     "student's solution.")
        else:
            intro = ("Course notes that may help (written for EduLite and checked for accuracy). Use them when "
                     "relevant and prefer them over memory if they disagree; ignore them if unrelated.")
        listed = "\n\n".join(f"[{i}] {title}\n{text}" for i, (title, text) in enumerate(notes, 1))
        parts.append(intro + "\n\n" + listed)
    return "\n\n".join(parts)
