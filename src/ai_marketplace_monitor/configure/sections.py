"""Generic AI-led section builders: field guides, drafts, and the conversation loop.

A builder gives an LLM a task (its playbook) plus field guides, and lets the LLM decide what
to ask. Completeness and validity are decided in code (``validate`` / ``missing``); the user
confirms the finished section before it is written.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple

from ..marketplace import FALLBACK, LOCATION
from .ui import SetupClosedError, SetupUI
from .writer import CommitOutcome, commit_config

if TYPE_CHECKING:
    from ..ai import AIBackend
    from .llm import Exchange
    from .playbooks import Playbook

# dataclass fields that are never configured through a builder
_NOT_CONFIGURED = {"name", "request", "monitor_config"}


class FieldGroup(Enum):
    OWN = "own"  # belongs to the section only
    SHARED = "shared"  # default for the section's items (option(...) fields)
    LOCATION = "location"  # shared, and part of the location group


@dataclass(frozen=True)
class FieldGuide:
    name: str
    determine: str  # how to work out the value
    format: str  # accepted values and examples
    default: str | None = None  # what happens at runtime when the field is unset
    secret: bool = False  # only ever a ${VAR} reference; never sent to the LLM


@dataclass
class SectionDraft:
    section_type: str
    name: str
    is_new: bool
    request: str | None
    values: Dict[str, Any]  # own fields + shared values, as one section
    varies: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # field -> {item: value}
    original: Dict[str, Any] = field(default_factory=dict)  # values when the draft was made
    all_items: Set[str] = field(default_factory=set)  # shared fields to set on every item

    def copy(self: "SectionDraft") -> "SectionDraft":
        return copy.deepcopy(self)


@dataclass
class TurnResult:
    draft: SectionDraft
    message: str
    complete: bool


class TurnError(Exception):
    """The LLM could not produce a usable reply."""


@dataclass
class BuilderContext:
    files: List[Path]
    system_cfg: Dict[str, Any]
    user_cfg: Dict[str, Any]
    expanded: Dict[str, Any]  # expand(user_cfg): what builders read and edit
    normalized: Dict[str, Any]  # normalize(user_cfg): what the user sees in their file
    backup_dir: Path
    playbooks: Dict[str, "Playbook"]
    ai: "AIBackend"


def field_group(cls: type, name: str) -> FieldGroup:
    """Group of a config field, read from its ``option(...)`` metadata."""
    for f in fields(cls):  # type: ignore[arg-type]
        if f.name == name:
            if f.metadata.get(LOCATION):
                return FieldGroup.LOCATION
            if f.metadata.get(FALLBACK):
                return FieldGroup.SHARED
            return FieldGroup.OWN
    raise KeyError(name)


def is_reference(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("${") and value.endswith("}")


class SectionBuilder:
    """Base class: subclasses declare their config class, guides and playbook."""

    section_type: str = ""
    playbook: str = ""
    config_class: type = object
    guides: Tuple[FieldGuide, ...] = ()
    max_turns = 15

    # --- field facts -------------------------------------------------------------------
    def field_names(self: "SectionBuilder") -> List[str]:
        return [f.name for f in fields(self.config_class) if f.name not in _NOT_CONFIGURED]  # type: ignore[arg-type]

    def group(self: "SectionBuilder", name: str) -> FieldGroup:
        return field_group(self.config_class, name)

    def guide(self: "SectionBuilder", name: str) -> FieldGuide:
        return next(g for g in self.guides if g.name == name)

    def guide_table(self: "SectionBuilder") -> str:
        """The field guides as markdown tables, one per group."""
        titles = {
            FieldGroup.OWN: "Fields of this section only",
            FieldGroup.LOCATION: "Location fields (defaults for items, set as a group)",
            FieldGroup.SHARED: "Shared fields (defaults for items; items may override)",
        }
        out = []
        for group, title in titles.items():
            rows = [g for g in self.guides if self.group(g.name) is group]
            if not rows:
                continue
            out.append(f"### {title}\n\n| field | how to determine | format | when unset |")
            out.append("|---|---|---|---|")
            for g in rows:
                secret = " **Secret: only a ${VAR} reference.**" if g.secret else ""
                out.append(
                    f"| `{g.name}` | {g.determine}{secret} | {g.format} | {g.default or ''} |"
                )
            out.append("")
        return "\n".join(out)

    def masked(self: "SectionBuilder", values: Dict[str, Any]) -> Dict[str, Any]:
        """Values safe to show the LLM: secret fields only as ``${VAR}`` references."""
        out = {}
        for key, value in values.items():
            secret = any(g.name == key and g.secret for g in self.guides)
            out[key] = value if not secret or is_reference(value) else "<set; hidden>"
        return out

    # --- section-specific behavior -------------------------------------------------------
    def context(
        self: "SectionBuilder", ctx: BuilderContext, draft: SectionDraft
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def view(self: "SectionBuilder", ctx: BuilderContext, name: str) -> SectionDraft:
        raise NotImplementedError

    def validate(self: "SectionBuilder", ctx: BuilderContext, draft: SectionDraft) -> List[str]:
        raise NotImplementedError

    def missing(self: "SectionBuilder", ctx: BuilderContext, draft: SectionDraft) -> List[str]:
        raise NotImplementedError

    def describe(self: "SectionBuilder", ctx: BuilderContext, draft: SectionDraft) -> str:
        raise NotImplementedError

    def apply(self: "SectionBuilder", ctx: BuilderContext, draft: SectionDraft) -> Dict[str, Any]:
        raise NotImplementedError

    async def choose_target(
        self: "SectionBuilder", ui: SetupUI, ctx: BuilderContext, name: str | None
    ) -> SectionDraft | None:
        raise NotImplementedError

    # --- the conversation ------------------------------------------------------------------
    async def run_turn(
        self: "SectionBuilder",
        ctx: BuilderContext,
        draft: SectionDraft,
        history: List["Exchange"],
        feedback: List[str],
    ) -> TurnResult:
        from .llm import run_turn

        return await run_turn(self, ctx, draft, history, feedback)

    async def converse(
        self: "SectionBuilder", ui: SetupUI, ctx: BuilderContext, name: str | None
    ) -> int:
        """Choose a section, let the LLM complete it, confirm, write. Returns an exit code."""
        from .llm import Exchange

        try:
            draft = await self.choose_target(ui, ctx, name)
            if draft is None:
                return 0
            history: List[Exchange] = []
            feedback: List[str] = []
            for _ in range(self.max_turns):
                try:
                    result = await self.run_turn(ctx, draft, history, feedback)
                except TurnError as e:
                    await ui.say(str(e), kind="error")
                    reply = await self._reply(
                        ui, ctx, draft, "Try saying it differently (or /quit)"
                    )
                    if reply is None:
                        return 0
                    history.append(Exchange("user", reply))
                    feedback = []
                    continue
                draft = result.draft
                history.append(Exchange("assistant", result.message))
                missing = self.missing(ctx, draft)
                if result.complete and missing:
                    # the LLM thinks it is done; tell it what is still required instead
                    feedback = [f"Still required: {m}" for m in missing]
                    continue
                feedback = []
                if result.complete:
                    await ui.say(result.message)
                    code = await self._review(ui, ctx, draft)
                    if code is not None:
                        return code
                    reply = await self._reply(ui, ctx, draft, "What would you like to change?")
                else:
                    await ui.say(result.message)
                    reply = await self._reply(ui, ctx, draft, "You")
                if reply is None:
                    return 0
                history.append(Exchange("user", reply))
            await ui.say(f"Stopping after {self.max_turns} turns with the AI.", kind="warning")
            if not self.missing(ctx, draft) and not self.validate(ctx, draft):
                code = await self._review(ui, ctx, draft)
                if code is not None:
                    return code
            return 0
        except SetupClosedError:
            return 0

    async def _review(
        self: "SectionBuilder", ui: SetupUI, ctx: BuilderContext, draft: SectionDraft
    ) -> int | None:
        """Show the section; on confirmation write it. None means "keep talking"."""
        await ui.say(self.describe(ctx, draft), markdown=True)
        if not await ui.confirm("Is this right?", default=True):
            return None
        outcome = await commit_config(
            ui, self.apply(ctx, draft), ctx.files, ctx.system_cfg, ctx.user_cfg, ctx.backup_dir
        )
        if outcome is CommitOutcome.WRITTEN:
            return 0
        if outcome is CommitOutcome.FAILED:
            return 1
        return None

    async def _reply(
        self: "SectionBuilder", ui: SetupUI, ctx: BuilderContext, draft: SectionDraft, prompt: str
    ) -> str | None:
        """The user's next message; handles /show and /quit. None means quit."""
        while True:
            reply = (await ui.ask_text(prompt, default="")).strip()
            if reply == "/quit":
                return None
            if reply == "/show":
                await ui.say(self.describe(ctx, draft), markdown=True)
                continue
            return reply


def builders() -> Dict[str, SectionBuilder]:
    """Registered builders, by section type."""
    from .marketplace import MarketplaceBuilder

    return {"marketplace": MarketplaceBuilder()}
