"""Conversation history passed to the model on every turn."""

from __future__ import annotations

from dataclasses import dataclass, field

# A short, neutral tutor persona. Full tutoring prompts (levels, modes, homework
# policy) are Milestone 4; this keeps Milestone 2 answers on topic and honest.
DEFAULT_SYSTEM_PROMPT = (
    "You are Edu.ai, a patient and accurate tutor for programming, computer science and AI. "
    "Explain clearly for students, use short Python examples when they help, and keep answers focused. "
    "If you are not sure about something, say so. Never claim that you ran or tested code."
)


@dataclass
class Conversation:
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    turns: list[dict] = field(default_factory=list)

    def messages(self) -> list[dict]:
        system = [{"role": "system", "content": self.system_prompt}] if self.system_prompt else []
        return system + list(self.turns)

    def add_user(self, text: str) -> None:
        self.turns.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        self.turns.append({"role": "assistant", "content": text})

    def undo_last_user(self) -> None:
        """Remove a trailing user message whose answer failed or was cancelled."""
        if self.turns and self.turns[-1]["role"] == "user":
            self.turns.pop()

    def drop_oldest_exchange(self) -> bool:
        """Forget the oldest user+assistant pair to free context. Keeps the latest message.

        Returns False when nothing more can be dropped.
        """
        if len(self.turns) <= 1:
            return False
        self.turns.pop(0)
        if self.turns and self.turns[0]["role"] == "assistant" and len(self.turns) > 1:
            self.turns.pop(0)
        return True

    def reset(self) -> None:
        self.turns.clear()

    @property
    def exchanges(self) -> int:
        return sum(1 for t in self.turns if t["role"] == "user")
