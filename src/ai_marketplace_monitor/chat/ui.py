"""The interface between the chat engine and its front ends."""

from typing import List, Protocol

from .messages import AskText, Choose, Confirm, Message, Question, Say

# An answer for ScriptedChatUI that simulates the user leaving (Ctrl-C, closed socket).
CLOSE = "<close>"


class ChatClosed(Exception):  # noqa: N818
    """The user left the conversation; nothing should be written."""


class ChatUI(Protocol):
    async def say(self: "ChatUI", message: Say) -> None: ...

    async def ask(self: "ChatUI", question: Question) -> str: ...


class ScriptedChatUI:
    """Front end for tests: returns canned answers in order and records every message."""

    def __init__(self: "ScriptedChatUI", answers: List[str]) -> None:
        self.answers = list(answers)
        self.transcript: List[Message] = []

    async def say(self: "ScriptedChatUI", message: Say) -> None:
        self.transcript.append(message)

    async def ask(self: "ScriptedChatUI", question: Question) -> str:
        self.transcript.append(question)
        if not self.answers:
            raise AssertionError(f"unexpected question: {question}")
        answer = self.answers.pop(0)
        if answer == CLOSE:
            raise ChatClosed
        # Handle empty answer mapping to defaults
        if not answer:
            if isinstance(question, Choose) and question.default is not None:
                return question.default
            if isinstance(question, Confirm):
                return "yes" if question.default else "no"
            if isinstance(question, AskText) and question.default is not None:
                return question.default
        # Validate non-empty answers
        if isinstance(question, Choose) and answer not in {o.value for o in question.options}:
            raise AssertionError(f"{answer!r} is not an option of {question}")
        if isinstance(question, Confirm) and answer not in ("yes", "no"):
            raise AssertionError(f"Confirm answers must be yes or no, got {answer!r}")
        return answer

    def said(self: "ScriptedChatUI", kind: str | None = None) -> List[str]:
        """Texts of the Say messages, optionally only those of one kind."""
        return [m.text for m in self.transcript if isinstance(m, Say) and kind in (None, m.kind)]
