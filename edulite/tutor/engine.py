"""Turns a conversation into model messages: level, mode, homework policy and course notes."""

from __future__ import annotations

from dataclasses import dataclass, field

from edulite.knowledge.retrieval import KnowledgeBase, default_knowledge_base, query_terms
from edulite.tutor.prompts import LEVELS, MODES, build_system_prompt, detect_mode

AUTO = "auto"
DEFAULT_LEVEL = "beginner"


@dataclass(frozen=True)
class PreparedTurn:
    messages: list[dict]
    mode: str
    detected: bool                       # True when the mode was chosen automatically
    sources: list[str] = field(default_factory=list)


class Tutor:
    def __init__(self, knowledge: KnowledgeBase | None = None):
        self._knowledge = knowledge

    @property
    def knowledge(self) -> KnowledgeBase:
        if self._knowledge is None:
            self._knowledge = default_knowledge_base()
        return self._knowledge

    def prepare(self, turns: list[dict], level: str = DEFAULT_LEVEL, mode: str = AUTO,
                use_notes: bool = True) -> PreparedTurn:
        """``turns`` is the chat so far (user/assistant), ending with the student's new message."""
        if level not in LEVELS:
            raise ValueError(f"Unknown level '{level}'. Choose one of: {', '.join(LEVELS)}")
        if mode != AUTO and mode not in MODES:
            raise ValueError(f"Unknown mode '{mode}'. Choose auto or one of: {', '.join(MODES)}")
        user_turns = [t["content"] for t in turns if t["role"] == "user"]
        if not user_turns:
            raise ValueError("The conversation must contain the student's message")
        latest = user_turns[-1]
        chosen = detect_mode(latest) if mode == AUTO else mode

        notes = []
        if use_notes:
            query = latest
            # A short follow-up ("why?", "show an example") is about the previous question.
            if len(query_terms(latest)) < 3 and len(user_turns) > 1:
                query = user_turns[-2] + "\n" + latest
            notes = [(p.title, p.text) for p in self.knowledge.search(query)]

        system = build_system_prompt(level, chosen, notes)
        return PreparedTurn(messages=[{"role": "system", "content": system}, *turns], mode=chosen,
                            detected=mode == AUTO, sources=[title for title, _ in notes])
