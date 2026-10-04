"""Section builders: everything aimm knows about creating or revising one section type."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple, Type

from ..ai import AIBackend
from .playbooks import PlaybookSet
from .ui import ChatUI


@dataclass
class SectionRef:
    type: str  # "ai", "item", "user", ...
    name: str | None = None  # None: create a new section

    @classmethod
    def parse(cls: Type["SectionRef"], text: str) -> "SectionRef":
        section_type, _, name = text.partition(".")
        return cls(section_type, name or None)

    def label(self: "SectionRef") -> str:
        return f"{self.type}.{self.name}" if self.name else self.type


@dataclass(frozen=True)
class FieldGuide:
    name: str  # a key the section accepts
    derive: str  # how to work out the value
    ask: str | None = None  # what to ask the user when it cannot be derived; None: never ask
    inherit: bool = True  # a new section copies it from its template section


@dataclass
class InterpretResult:
    values: Dict[str, Any]  # proposed field values (raw, e.g. "${VAR}")
    notes: List[str] = field(default_factory=list)  # what to tell the user
    questions: List[str] = field(default_factory=list)  # still needed; empty = complete


@dataclass
class SectionProposal:
    ref: SectionRef  # name filled in
    values: Dict[str, Any]  # raw keys, e.g. {"api_key": "${UNITYSVC_API_KEY}"}
    request: str | None  # one-sentence summary of what the user asked for
    target_file: Path


@dataclass
class ChatContext:
    files: List[Path]  # config files in read order
    default_file: Path  # ~/.ai-marketplace-monitor/config.toml
    playbooks: PlaybookSet
    backup_dir: Path  # ~/.ai-marketplace-monitor/backups
    ai: AIBackend | None = None  # the chat's AI; None until it is chosen


class SectionBuilder:
    """Base class: one subclass per section type.

    Subclasses set ``section_type``, ``playbook`` (bundled playbook name), ``uses_ai``, and
    ``fields`` (how to derive each field and what to ask). The generic AI-backed
    ``interpret`` and ``converse`` arrive with the first AI-driven builder; scripted builders
    override ``converse``.
    """

    section_type: str = ""
    playbook: str = ""
    uses_ai: bool = True
    fields: Tuple[FieldGuide, ...] = ()

    def guide_text(self: "SectionBuilder") -> str:
        lines = [f"# Field guide for [{self.section_type}.*] sections", ""]
        for guide in self.fields:
            line = f"- `{guide.name}`: {guide.derive}"
            if guide.ask:
                line += f" Ask: {guide.ask}"
            if guide.inherit:
                line += " (shared: copied from an existing section when creating a new one)"
            lines.append(line)
        return "\n".join(lines)

    def instructions(self: "SectionBuilder", ctx: ChatContext) -> str:
        playbook = ctx.playbooks.sections.get(self.playbook)
        parts = [playbook.text()] if playbook else []
        return "\n\n".join([*parts, self.guide_text()])

    def template_values(self: "SectionBuilder", template: Dict[str, Any]) -> Dict[str, Any]:
        """Fields a new section copies from an existing section of the same type."""
        inherited = {g.name for g in self.fields if g.inherit}
        return {k: v for k, v in template.items() if k in inherited}

    def interpret(
        self: "SectionBuilder", current: Dict[str, Any], request: str, ctx: ChatContext
    ) -> InterpretResult:
        raise NotImplementedError(
            f"{type(self).__name__} has no interpret step; the AI-backed one comes later."
        )

    async def converse(
        self: "SectionBuilder", ui: ChatUI, ref: SectionRef, ctx: ChatContext
    ) -> SectionProposal | None:
        raise NotImplementedError(
            f"{type(self).__name__} has no conversation; the AI-backed one comes later."
        )

    async def after_commit(
        self: "SectionBuilder", ui: ChatUI, proposal: SectionProposal, ctx: ChatContext
    ) -> Any:
        return None
