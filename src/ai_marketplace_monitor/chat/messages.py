"""Messages exchanged between the chat engine and a front end (JSON-serializable)."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Union


class _Message:
    def to_dict(self: "_Message") -> Dict[str, Any]:
        return {"type": _NAMES[type(self)], **asdict(self)}  # type: ignore[call-overload]


@dataclass
class Say(_Message):
    text: str
    kind: str = "info"  # info | success | warning | error | assistant
    markdown: bool = False


@dataclass
class Option:
    value: str
    label: str
    hint: str = ""


@dataclass
class Choose(_Message):
    prompt: str
    options: List[Option] = field(default_factory=list)
    default: str | None = None


@dataclass
class AskText(_Message):
    prompt: str
    default: str | None = None


@dataclass
class Confirm(_Message):
    prompt: str
    default: bool = True


Question = Union[Choose, AskText, Confirm]
Message = Union[Say, Choose, AskText, Confirm]

_TYPES: Dict[str, type] = {"say": Say, "choose": Choose, "ask_text": AskText, "confirm": Confirm}
_NAMES: Dict[type, str] = {cls: name for name, cls in _TYPES.items()}


def message_from_dict(data: Dict[str, Any]) -> Message:
    """Inverse of ``to_dict``."""
    values = dict(data)
    cls = _TYPES[values.pop("type")]
    if cls is Choose:
        values["options"] = [Option(**o) for o in values.get("options", [])]
    return cls(**values)  # type: ignore[no-any-return]
