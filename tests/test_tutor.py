import pytest

from edulite.knowledge.retrieval import KnowledgeBase, parse_notes, query_terms
from edulite.tutor.engine import Tutor
from edulite.tutor.prompts import LEVELS, MODES, build_system_prompt, detect_mode


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase()


# ---------------------------------------------------------------- retrieval

def test_notes_are_indexed(kb):
    assert kb.size >= 60
    assert {"Python basics", "Algorithms and data structures", "AI and machine learning foundations"} <= set(kb.sources)


def test_every_note_section_has_content():
    from edulite.knowledge.retrieval import NOTES_DIR
    for path in NOTES_DIR.glob("*.md"):
        for source, section, text in parse_notes(path):
            assert len(text) > 150, f"{path.name}: '{section}' is too short"


@pytest.mark.parametrize("question, expected", [
    ("What is the difference between a list and a tuple?", {"Tuples", "Lists"}),
    ("explain gradient descent simply", {"Gradient descent and the learning rate"}),
    ("what is precision and recall", {"Evaluation metrics: accuracy, precision, recall, F1 and the confusion matrix"}),
    ("how do I read a file line by line", {"Reading and writing files"}),
    ("SELECT with GROUP BY and HAVING", {"SQL basics: querying tables"}),
    ("why does my recursion never stop", {"Recursion"}),
])
def test_relevant_sections_are_found(kb, question, expected):
    found = {p.section for p in kb.search(question)}
    assert expected <= found, found


@pytest.mark.parametrize("small_talk", ["hi, how are you?", "thanks!", "I have another question",
                                        "what is the capital of France"])
def test_off_topic_messages_retrieve_nothing(kb, small_talk):
    assert kb.search(small_talk) == []


def test_search_syntax_in_user_text_is_harmless(kb):
    assert kb.search('he said "OR NOT" AND (x* NEAR/3 -') == []
    assert kb.search('"tuple"') != []


def test_retrieved_text_respects_budget(kb):
    passages = kb.search("sorting algorithms quicksort merge sort bubble insertion", k=3, max_chars=1500)
    assert sum(len(p.text) for p in passages) <= 1500 or len(passages) == 1


def test_query_terms_drop_stopwords_and_duplicates():
    assert query_terms("What is the difference between a list and a list?") == ["list"]
    assert query_terms("C++ and C# basics") == ["c++", "c#", "basics"]


# -------------------------------------------------------------- mode detection

@pytest.mark.parametrize("message, mode", [
    ("What is a Python variable?", "explain"),
    ("Write a function that reverses a string", "code"),
    ("I get TypeError: can only concatenate str to str", "debug"),
    ("Why does my loop skip the first item?", "debug"),
    ("I'm stuck on my homework: find the largest number in a list", "hint"),
    ("Give me a hint for FizzBuzz", "hint"),
    ("This is an assignment, just give me the full solution", "code"),
    ("Quiz me on Python loops", "quiz"),
    ("Help me build a mini project: a quiz app", "project"),
    ("Translate this Python code to Java", "code"),
    ("hello", "explain"),
])
def test_detect_mode(message, mode):
    assert detect_mode(message) == mode


# Regression tests for P1 (milestone-4-issues.md): keywords alone must not trigger Debug.
@pytest.mark.parametrize("message", [
    # conceptual questions mentioning exceptions / errors / bugs
    "Which keyword introduces the block that handles an exception in Python?",
    "What does a KeyError mean?",
    "Why does a RecursionError happen?",
    "Why is def add(item, items=[]) a common bug?",
    "A model with very low training error but high test error is most likely:\nA. Overfitting\nB. Underfitting",
    "What does len([1, [2, 3], 4]) return?\nA. 4\nB. 3\nC. It raises an error",
    # debugging as a general topic
    "What are good debugging strategies for beginners?",
    "Explain what a traceback is.",
    "How do try and except work?",
    # explaining code is not debugging it
    "Explain this code:\n```python\ntry:\n    x = int(s)\nexcept ValueError:\n    x = 0\n```",
])
def test_conceptual_questions_are_explain(message):
    assert detect_mode(message) == "explain"


@pytest.mark.parametrize("message", [
    # code snippet with an actual problem
    "This prints the wrong total:\n```python\ntotal = 0\nfor i in range(1, len(nums)):\n    total += nums[i]\n```",
    "```python\ndef f(n):\n    return n * f(n - 1)\n```\nIt crashes, why?",
    # traceback without full source
    'Traceback (most recent call last):\n  File "main.py", line 3, in <module>\nNameError: name \'x\' is not defined',
    "I get IndexError: list index out of range on line 4",
    # explicit requests to debug own code
    "Can you fix my code? It doesn't work.",
    "Why does my function return None?",
    "What's wrong with this loop?",
    "Please debug my program, the output is wrong",
])
def test_concrete_problems_are_debug(message):
    assert detect_mode(message) == "debug"


@pytest.mark.parametrize("message, mode", [
    ("Give me a hint, here is my attempt:\n```python\ndef largest(nums):\n    m = 0\n```", "hint"),
    ("Can I have the next hint?", "hint"),
    ("Another hint please, I'm still stuck", "hint"),
    ("I'm stuck on my homework, just give me the full solution", "code"),
    ("Explain this concept: recursion", "explain"),
])
def test_explicit_intent_wins(message, mode):
    assert detect_mode(message) == mode


# ------------------------------------------------------------------- prompts

def test_prompt_contains_level_mode_and_honesty_rules():
    prompt = build_system_prompt("beginner", "debug")
    assert LEVELS["beginner"] in prompt and MODES["debug"] in prompt
    assert "Never claim you ran or tested code" in prompt
    assert "Course notes" not in prompt  # no notes section when nothing was retrieved


def test_hint_mode_withholds_the_solution():
    assert "Do NOT give the full solution" in build_system_prompt("intermediate", "hint")


def test_prompt_stays_small():
    # Leaves room for history and the answer in a 4,096-token context.
    assert len(build_system_prompt("advanced", "project")) < 1200


# --------------------------------------------------------------------- tutor

def test_prepare_adds_notes_and_reports_sources(kb):
    turn = Tutor(kb).prepare([{"role": "user", "content": "What is a tuple in Python?"}])
    assert turn.mode == "explain" and turn.detected
    assert "Python collections › Tuples" in turn.sources
    assert "Tuples" in turn.messages[0]["content"] and turn.messages[0]["role"] == "system"
    assert turn.messages[-1] == {"role": "user", "content": "What is a tuple in Python?"}


def test_short_follow_up_uses_previous_question_for_notes(kb):
    turns = [{"role": "user", "content": "Explain gradient descent"},
             {"role": "assistant", "content": "It is ..."},
             {"role": "user", "content": "why?"}]
    sources = Tutor(kb).prepare(turns).sources
    assert any("Gradient descent" in s for s in sources)


def test_explicit_mode_and_notes_off(kb):
    turn = Tutor(kb).prepare([{"role": "user", "content": "What is a tuple?"}], level="advanced",
                             mode="quiz", use_notes=False)
    assert turn.mode == "quiz" and not turn.detected and turn.sources == []
    assert LEVELS["advanced"] in turn.messages[0]["content"]


def test_invalid_level_or_mode(kb):
    with pytest.raises(ValueError):
        Tutor(kb).prepare([{"role": "user", "content": "x"}], level="expert")
    with pytest.raises(ValueError):
        Tutor(kb).prepare([{"role": "user", "content": "x"}], mode="essay")


# ------------------------------------------------------------ P2/P4 regressions

from edulite.tutor.prompts import FORMAT_PRIORITY, HINT_PLACEHOLDER, redact_worked_solutions  # noqa: E402


def test_format_priority_comes_before_teaching_steps():
    prompt = build_system_prompt("beginner", "debug")
    assert prompt.index(FORMAT_PRIORITY) < prompt.index("Task:")


def test_debug_mode_is_code_first_without_forced_sections_or_analogies():
    debug = MODES["debug"]
    assert debug.index("corrected code") < debug.index("what caused the bug")
    assert "1)" not in debug and "analogy" not in debug.lower()
    assert "only if it makes the idea clearer" in LEVELS["beginner"]


def test_redaction_removes_worked_solutions_but_keeps_concepts():
    note = ("Binary search halves the range each step.\n"
            "```python\ndef binary_search(arr, target):\n    low, high = 0, len(arr) - 1\n    return -1\n```\n"
            "Use `sorted()` first. Short syntax example:\n```python\nx = [1, 2]\n```\n"
            "A loop example:\n```python\nfor x in items:\n    if x not in seen:\n        seen.append(x)\n```")
    redacted = redact_worked_solutions(note)
    assert "def binary_search" not in redacted and "seen.append" not in redacted
    assert redacted.count(HINT_PLACEHOLDER) == 2
    assert "Binary search halves the range" in redacted and "`sorted()`" in redacted and "x = [1, 2]" in redacted


def test_hint_mode_notes_are_redacted_other_modes_keep_code(kb):
    turns = [{"role": "user", "content": "I'm stuck on homework: write binary_search(arr, target) for a sorted list"}]
    hint = Tutor(kb).prepare(turns)
    assert hint.mode == "hint" and hint.sources
    assert "def binary_search" not in hint.messages[0]["content"]
    assert "not to write the student's solution" in hint.messages[0]["content"]
    explain = Tutor(kb).prepare([{"role": "user", "content": "Explain binary search with code"}], mode="explain")
    assert "def binary_search" in explain.messages[0]["content"]  # code examples still help explanations
