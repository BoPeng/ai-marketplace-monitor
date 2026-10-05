"""The configure tools: everything the LLM can do, implemented by aimm.

The LLM changes nothing directly. It drafts sections with ``<type>_update`` (validated here),
talks to the user with ``ask_user``, and saves with ``save``, which shows the change and asks
the user before ``commit_sections`` writes only the drafted sections. Tools return dicts; errors
are returned, never raised, so the LLM can correct itself.

This module does not depend on any LLM library; ``tools_for_model()`` wraps the tools as plain
async functions with signatures and docstrings for the model adapter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Tuple

from .toolkits import Toolkit
from .ui import SetupClosedError
from .workspace import ConfigLoadError, SectionKey, Workspace
from .writer import CommitOutcome, commit_sections

# section types listed by list_sections, in config order
SECTION_TYPES = ("ai", "marketplace", "user", "notification", "region", "item", "translation")


class Outcome(Enum):
    SAVED = "saved"  # something was written
    UNCHANGED = "unchanged"  # the session ended without writing (nothing to write)
    CANCELLED = "cancelled"  # the user stopped, or unsaved changes were discarded
    FAILED = "failed"  # the config could not be read or written


@dataclass
class ToolExecutor:
    ws: Workspace
    # a single-section command: section tools work on this section only
    only: SectionKey | None = None
    # runs `aimm-configure ai` (offered by the aimm-configure wrapper only); returns exit code
    setup_ai: Callable[[], Awaitable[int]] | None = None
    done: bool = False
    closed: bool = False  # the user closed the input (Ctrl-C)
    saved: bool = False
    failed: bool = False
    discarded: bool = False
    steps_without_user: int = 0  # tool calls since the user last said something
    force_ask: bool = False  # set by the agent loop: only ask_user / finish are allowed
    calls: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)

    # --- state ------------------------------------------------------------------------------
    @property
    def outcome(self: "ToolExecutor") -> Outcome:
        if self.failed and not self.saved:
            return Outcome.FAILED
        if self.saved:
            return Outcome.SAVED
        return Outcome.CANCELLED if self.discarded else Outcome.UNCHANGED

    def end(self: "ToolExecutor", *, discarded: bool = False) -> None:
        self.done = True
        self.discarded = self.discarded or discarded

    # --- talking to the user ----------------------------------------------------------------
    async def read_user(self: "ToolExecutor", prompt: str = "You") -> str | None:
        """The user's next message, or None if they quit (/quit or Ctrl-C)."""
        try:
            while True:
                reply = (await self.ws.ui.ask_text(prompt, default="")).strip()
                if reply == "/quit":
                    self.end(discarded=bool(self.ws.pending()))
                    return None
                if reply == "/show":
                    await self.show_drafts()
                    continue
                self.steps_without_user = 0
                return reply
        except SetupClosedError:
            self.closed = True
            self.end(discarded=bool(self.ws.pending()))
            return None

    async def show_drafts(self: "ToolExecutor") -> None:
        drafts = list(self.ws.drafts.values())
        if not drafts:
            await self.ws.ui.say("Nothing has been drafted yet.")
        for draft in drafts:
            await self.ws.ui.say(
                self.ws.toolkits[draft.section_type].describe(draft), markdown=True
            )

    async def ask_user(self: "ToolExecutor", message: str) -> Dict[str, Any]:
        await self.ws.ui.say(message)
        reply = await self.read_user()
        if reply is None:
            return {"ok": True, "reply": None, "note": "The user ended the session."}
        return {"ok": True, "reply": reply}

    # --- the config index -------------------------------------------------------------------
    async def list_sections(self: "ToolExecutor") -> Dict[str, Any]:
        cfg = self.ws.user_cfg
        types = []
        for section_type in SECTION_TYPES:
            configurable = section_type in self.ws.toolkits or (
                section_type == "ai" and self.setup_ai is not None
            )
            body = cfg.get(section_type, {})
            sections = [
                {"name": name, "request": section.get("request")}
                for name, section in body.items()
                if isinstance(section, dict)
            ]
            if sections or configurable:
                types.append(
                    {"type": section_type, "configurable_here": configurable, "sections": sections}
                )
        return {"ok": True, "section_types": types}

    # --- section tools ----------------------------------------------------------------------
    def _toolkit(
        self: "ToolExecutor", section_type: str, name: str
    ) -> Tuple[Toolkit | None, str | None]:
        if section_type not in self.ws.toolkits:
            return None, f"[{section_type}.*] sections cannot be configured here."
        if self.only is not None and (section_type, name) != self.only:
            return None, f"Only [{self.only[0]}.{self.only[1]}] can be changed in this session."
        if not name or not isinstance(name, str):
            return None, "A section name is required."
        return self.ws.toolkits[section_type], None

    def _summary(self: "ToolExecutor", toolkit: Toolkit, key: SectionKey) -> Dict[str, Any]:
        draft = self.ws.draft(*key)
        return {
            "section": f"{key[0]}.{key[1]}",
            "exists": not draft.is_new,
            "request": draft.request,
            "saved_values": toolkit.masked(draft.original),
            "values": toolkit.masked(draft.values),
            "unsaved_changes": toolkit.masked(draft.unsaved_changes()),
            "still_required": toolkit.missing(self.ws, draft),
        }

    async def section_show(self: "ToolExecutor", section_type: str, name: str) -> Dict[str, Any]:
        toolkit, error = self._toolkit(section_type, name)
        if toolkit is None:
            return {"ok": False, "errors": [error]}
        return {
            "ok": True,
            **self._summary(toolkit, (section_type, name)),
            "can_reference": toolkit.context(self.ws),
        }

    async def section_update(
        self: "ToolExecutor",
        section_type: str,
        name: str,
        values: Dict[str, Any] | str | None = None,
        unset: List[str] | None = None,
        request: str | None = None,
    ) -> Dict[str, Any]:
        toolkit, error = self._toolkit(section_type, name)
        if toolkit is None:
            return {"ok": False, "errors": [error]}
        # `values` is a JSON object in a string (free-form objects do not survive every
        # provider's tool schema); a dict is accepted too
        # some models encode the string twice ("\"{...}\""): decode at most twice
        for _ in range(2):
            if not isinstance(values, str):
                break
            try:
                values = json.loads(values) if values.strip() else {}
            except ValueError as e:
                return {"ok": False, "errors": [f"`values` is not valid JSON: {e}"]}
        changes = values or {}
        if not isinstance(changes, dict) or not isinstance(unset or [], list):
            return {
                "ok": False,
                "errors": [
                    (
                        '`values` must be one JSON object, e.g. {"radius": [20]}, and `unset` '
                        "a list of field names."
                    )
                ],
            }
        draft = self.ws.draft(section_type, name)
        candidate, problems = toolkit.change(draft, changes, unset or [], request)
        errors = problems or toolkit.validate(self.ws, candidate)
        if errors:
            return {"ok": False, "errors": errors, "note": "The draft was not changed."}
        self.ws.drafts[(section_type, name)] = candidate
        return {"ok": True, **self._summary(toolkit, (section_type, name))}

    async def section_check(self: "ToolExecutor", section_type: str, name: str) -> Dict[str, Any]:
        toolkit, error = self._toolkit(section_type, name)
        if toolkit is None:
            return {"ok": False, "errors": [error]}
        draft = self.ws.draft(section_type, name)
        return {
            "ok": True,
            "still_required": toolkit.missing(self.ws, draft),
            "errors": toolkit.validate(self.ws, draft),
            "unsaved_changes": toolkit.masked(draft.unsaved_changes()),
        }

    # --- saving and ending ------------------------------------------------------------------
    async def save(self: "ToolExecutor", message: str) -> Dict[str, Any]:
        pending = self.ws.pending()
        if not pending:
            return {"ok": True, "saved": False, "note": "Nothing to save: no unsaved changes."}
        errors: List[str] = []
        for draft in pending:
            toolkit = self.ws.toolkits[draft.section_type]
            errors += [
                f"{draft.label}: still required: {m}" for m in toolkit.missing(self.ws, draft)
            ]
            errors += [f"{draft.label}: {e}" for e in toolkit.validate(self.ws, draft)]
        if errors:
            return {"ok": False, "errors": errors, "note": "Nothing was saved."}
        if message:
            await self.ws.ui.say(message)
        new_cfg = self.ws.user_cfg
        for draft in pending:
            toolkit = self.ws.toolkits[draft.section_type]
            await self.ws.ui.say(toolkit.describe(draft), markdown=True)
            new_cfg = toolkit.apply(new_cfg, draft)
        try:
            outcome = await commit_sections(
                self.ws.ui,
                new_cfg,
                self.ws.user_cfg,
                self.ws.files,
                self.ws.backup_dir,
                only=[draft.key for draft in pending],
            )
        except SetupClosedError:
            self.closed = True
            self.end(discarded=True)
            return {"ok": True, "saved": False, "note": "The user ended the session."}
        if outcome is CommitOutcome.DECLINED:
            return {
                "ok": True,
                "saved": False,
                "declined": True,
                "note": "The user did not want to write this; ask what to change.",
            }
        if outcome is CommitOutcome.FAILED:
            self.failed = True
            return {"ok": False, "errors": ["The change could not be written (see the message)."]}
        self.saved = True
        for draft in pending:
            del self.ws.drafts[draft.key]
        try:
            await self.ws.load()
        except ConfigLoadError as e:
            await self.ws.ui.say(str(e), kind="error")
        return {"ok": True, "saved": True, "sections": [d.label for d in pending]}

    async def finish(
        self: "ToolExecutor", message: str, discard_unsaved: bool = False
    ) -> Dict[str, Any]:
        pending = self.ws.pending()
        if pending and not discard_unsaved:
            changes = "; ".join(
                f"{d.label}: "
                + ", ".join(
                    f"{k}={v!r}"
                    for k, v in self.ws.toolkits[d.section_type]
                    .masked(d.unsaved_changes())
                    .items()
                )
                for d in pending
            )
            return {
                "ok": False,
                "errors": [
                    (
                        f"There are unsaved changes ({changes}). Call save to keep them, or "
                        "finish with discard_unsaved=true only if the user wants to discard them."
                    )
                ],
            }
        if message:
            await self.ws.ui.say(message)
        if pending:
            await self.ws.ui.say("Unsaved changes were discarded.", kind="warning")
        self.end(discarded=bool(pending))
        return {"ok": True}

    async def run_setup_ai(self: "ToolExecutor") -> Dict[str, Any]:
        if self.setup_ai is None:
            return {"ok": False, "errors": ["AI setup is not available here."]}
        code = await self.setup_ai()
        try:
            await self.ws.load()
        except ConfigLoadError as e:
            return {"ok": False, "errors": [str(e)]}
        return {"ok": code == 0}

    # --- dispatch -------------------------------------------------------------------------
    def tools_for_model(self: "ToolExecutor") -> List[Callable[..., Awaitable[Dict[str, Any]]]]:
        """The tools as named async functions with signatures and docstrings."""
        tools: List[Callable[..., Awaitable[Dict[str, Any]]]] = []

        async def ask_user(message: str) -> Dict[str, Any]:
            """Say something to the user and wait for their reply. Use it for every question.

            Args:
                message: what to say: your question, with the settings that can be set or
                    changed and their current values when you ask what to change.
            """
            return await self.call("ask_user", {"message": message})

        async def save(message: str) -> Dict[str, Any]:
            """Save all sections with unsaved changes.

            aimm shows the change and asks the user to confirm before writing; it refuses
            incomplete or invalid sections.

            Args:
                message: a short summary of what is about to be saved (do not say it is saved).
            """
            return await self.call("save", {"message": message})

        async def finish(message: str, discard_unsaved: bool = False) -> Dict[str, Any]:
            """End the session.

            Refused while there are unsaved changes, unless discard_unsaved is true because the
            user wants to discard them.

            Args:
                message: closing message for the user.
                discard_unsaved: true only if the user wants to discard unsaved changes.
            """
            return await self.call(
                "finish", {"message": message, "discard_unsaved": discard_unsaved}
            )

        tools += [ask_user, save, finish]
        if self.only is None:

            async def list_sections() -> Dict[str, Any]:
                """List the section types and sections, with names and requests only.

                Each section's `request` says what the user wanted from it; contents are not
                shown.
                """
                return await self.call("list_sections", {})

            tools.append(list_sections)
        if self.setup_ai is not None:

            async def setup_ai() -> Dict[str, Any]:
                """Run the interactive AI service setup (`aimm-configure ai`) for the user."""
                return await self.call("setup_ai", {})

            tools.append(setup_ai)
        for section_type in self.ws.toolkits:
            tools += _section_tools(self, section_type)
        return tools

    async def call(self: "ToolExecutor", name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Run a tool by name (used by the model adapter and by tests)."""
        self.calls.append((name, args))
        if name != "ask_user":
            self.steps_without_user += 1
        if self.done:
            return {"ok": False, "errors": ["The session has ended."]}
        if self.force_ask and name not in ("ask_user", "finish"):
            return {
                "ok": False,
                "errors": ["Too many steps without the user: call ask_user now."],
            }
        try:
            if name == "ask_user":
                return await self.ask_user(str(args.get("message", "")))
            if name == "list_sections":
                return await self.list_sections()
            if name == "save":
                return await self.save(str(args.get("message", "")))
            if name == "finish":
                return await self.finish(
                    str(args.get("message", "")), bool(args.get("discard_unsaved", False))
                )
            if name == "setup_ai":
                return await self.run_setup_ai()
            section_type, _, action = name.rpartition("_")
            if section_type in self.ws.toolkits and action in ("show", "update", "check"):
                section_name = args.get("name", "")
                if action == "show":
                    return await self.section_show(section_type, section_name)
                if action == "check":
                    return await self.section_check(section_type, section_name)
                return await self.section_update(
                    section_type,
                    section_name,
                    args.get("values"),
                    args.get("unset"),
                    args.get("request"),
                )
        except SetupClosedError:
            self.closed = True
            self.end(discarded=bool(self.ws.pending()))
            return {"ok": True, "note": "The user ended the session."}
        return {"ok": False, "errors": [f"Unknown tool `{name}`."]}


def _section_tools(
    executor: ToolExecutor, section_type: str
) -> List[Callable[..., Awaitable[Dict[str, Any]]]]:
    label = f"[{section_type}.NAME]"

    async def show(name: str) -> Dict[str, Any]:
        return await executor.call(f"{section_type}_show", {"name": name})

    async def update(
        name: str,
        values: str = "",
        unset: List[str] | None = None,
        request: str | None = None,
    ) -> Dict[str, Any]:
        return await executor.call(
            f"{section_type}_update",
            {"name": name, "values": values, "unset": unset, "request": request},
        )

    async def check(name: str) -> Dict[str, Any]:
        return await executor.call(f"{section_type}_check", {"name": name})

    show.__doc__ = f"""Show the section {label}: its saved values, the values in this session,
    unsaved changes, what is still required, and the names its fields may reference.

    Args:
        name: the section name, e.g. "facebook".
    """
    update.__doc__ = f"""Change the draft of {label}; nothing is written until save. aimm
    validates the result and returns errors (the draft is then unchanged).

    Args:
        name: the section name.
        values: the fields to set, as a JSON object in a string, e.g.
            '{{"search_city": ["houston"], "radius": [30]}}'. Empty to set nothing.
        unset: fields to remove.
        request: one or two sentences: what the user wants from this section, in their terms.
    """
    check.__doc__ = f"""Check the draft of {label}: what is still required, validation errors,
    and unsaved changes.

    Args:
        name: the section name.
    """
    tools: List[Callable[..., Awaitable[Dict[str, Any]]]] = []
    for fn, action in ((show, "show"), (update, "update"), (check, "check")):
        fn.__name__ = fn.__qualname__ = f"{section_type}_{action}"
        tools.append(fn)
    return tools
