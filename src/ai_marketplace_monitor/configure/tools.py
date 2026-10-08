"""The configure tools: everything the LLM can do, implemented by aimm.

The LLM changes nothing directly. It drafts sections with ``section_update`` (validated here),
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
from typing import Any, Awaitable, Callable, Dict, List, Sequence, Set, Tuple

from .toolkits import SINGLETONS, Toolkit, location, section_label
from .ui import SetupClosedError
from .workspace import ConfigLoadError, SectionKey, Workspace
from .writer import CommitOutcome, commit_sections

# section types listed by list_sections, in config order
SECTION_TYPES = (
    "ai",
    "marketplace",
    "user",
    "notification",
    "region",
    "item",
    "translation",
    "monitor",
)


def section_index(ws: Workspace) -> List[Dict[str, Any]]:
    """The saved sections by type: name, `request`, a short summary, and whether disabled."""
    types = []
    for section_type in SECTION_TYPES:
        toolkit = ws.toolkits.get(section_type)
        body = ws.user_cfg.get(section_type, {})
        if section_type in SINGLETONS:  # [monitor]: one section named after its type
            found = {section_type: body} if body else {}
        else:
            found = {n: v for n, v in body.items() if isinstance(v, dict)}
        sections = []
        for name, values in found.items():
            entry: Dict[str, Any] = {"name": name, "request": values.get("request")}
            summary = toolkit.summary(ws, values) if toolkit else None
            if summary:
                entry["summary"] = summary
            if values.get("enabled") is False:
                entry["disabled"] = True
            sections.append(entry)
        if sections or toolkit:
            types.append(
                {"type": section_type, "configurable_here": bool(toolkit), "sections": sections}
            )
    return types


def monitoring_needs(ws: Workspace) -> List[str]:
    """What aimm still needs to search and notify, in the order to set it up."""
    from .notify import notified_via  # notify's toolkits import the tools' helpers

    def enabled(section_type: str) -> List[Dict[str, Any]]:
        body = ws.user_cfg.get(section_type, {})
        return [v for v in body.values() if isinstance(v, dict) and v.get("enabled") is not False]

    items = [v for v in enabled("item") if v.get("search_phrases")]
    missing: List[str] = []
    if not any(location(v) for v in enabled("marketplace") + items):
        missing.append("a search location (marketplace)")
    if not any(notified_via(ws, v) for v in enabled("user")):
        missing.append("a way to notify the user (notification)")
    if not items:
        missing.append("an item to search for (item)")
    return missing


def how_to_run(monitor_running: bool, missing: Sequence[str] = ()) -> str:
    """What the user must do for a saved change to take effect: saving starts nothing."""
    if missing:
        return (
            "Your configuration is saved, but aimm still needs "
            f"{'; '.join(m.split(' (')[0] for m in missing)} before it can monitor anything. "
            "Run `aimm configure` again to add " + ("it." if len(missing) == 1 else "them.")
        )
    if monitor_running:
        return "Your configuration is saved; the running monitor picks up the change on its own."
    return (
        "Your configuration is saved, but nothing is searching yet: run `aimm run` to start "
        "monitoring (a monitor that is already running picks up the change on its own)."
    )


class Outcome(Enum):
    SAVED = "saved"  # something was written
    UNCHANGED = "unchanged"  # the session ended without writing (nothing to write)
    CANCELLED = "cancelled"  # the user stopped, or unsaved changes were discarded
    FAILED = "failed"  # the config could not be read or written


@dataclass
class ToolExecutor:
    ws: Workspace
    # a single-section command: section tools work on these sections only (the chosen
    # section, and companions such as an item's marketplace)
    only: Set[SectionKey] | None = None
    done: bool = False
    closed: bool = False  # the user closed the input (Ctrl-C)
    saved: bool = False
    failed: bool = False
    discarded: bool = False
    steps_without_user: int = 0  # tool calls since the user last said something
    force_ask: bool = False  # set by the agent loop: only ask_user / finish are allowed
    calls: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    # section types whose guide (playbook + field table) the model has read
    guides_read: Set[str] = field(default_factory=set)
    # saved sections aimm offers to try with test_notification (e.g. a notification channel)
    testable: Set[SectionKey] = field(default_factory=set)

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
                self.ws.user_said.append(reply)
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
        await self.ws.ui.say(message, kind="assistant")
        reply = await self.read_user()
        if reply is None:
            return {"ok": True, "reply": None, "note": "The user ended the session."}
        return {"ok": True, "reply": reply}

    # --- the config index -------------------------------------------------------------------
    async def list_sections(self: "ToolExecutor") -> Dict[str, Any]:
        return {"ok": True, "section_types": section_index(self.ws)}

    # --- section tools ----------------------------------------------------------------------
    def _toolkit(
        self: "ToolExecutor", section_type: str, name: str
    ) -> Tuple[Toolkit | None, str | None]:
        if section_type not in self.ws.toolkits:
            return None, f"[{section_type}.*] sections cannot be configured here."
        if (
            self.only is not None
            and (section_type, name) not in self.only
            and (section_type, "*") not in self.only
        ):
            allowed = ", ".join(section_label(t, n) for t, n in sorted(self.only))
            return None, f"Only {allowed} can be changed in this session."
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
        draft = self.ws.draft(section_type, name)
        return {
            "ok": True,
            **self._summary(toolkit, (section_type, name)),
            **toolkit.show_extra(self.ws, draft),
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
        if section_type not in self.guides_read:
            return {
                "ok": False,
                "errors": [f"Read the rules first: call section_guide({section_type!r})."],
            }
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
            **await toolkit.check_extra(self.ws, draft),
        }

    async def section_guide(self: "ToolExecutor", section_type: str) -> Dict[str, Any]:
        if section_type not in self.ws.toolkits:
            return {
                "ok": False,
                "errors": [f"[{section_type}.*] sections cannot be configured here."],
            }
        toolkit = self.ws.toolkits[section_type]
        # types that share a playbook (users and notifications) are read together
        types = [t for t, k in self.ws.toolkits.items() if k.playbook == toolkit.playbook]
        self.guides_read.update(types)
        return {
            "ok": True,
            "section_type": section_type,
            "playbook": self.ws.playbooks[toolkit.playbook].text(),
            "fields": "\n\n".join(self.ws.toolkits[t].guide_table() for t in types),
        }

    def session_state(self: "ToolExecutor") -> Dict[str, Any]:
        """What is being worked on: drafted sections, their unsaved changes, completeness."""
        drafts = []
        for draft in self.ws.drafts.values():
            toolkit = self.ws.toolkits[draft.section_type]
            drafts.append(
                {
                    "section": f"{draft.section_type}.{draft.name}",
                    "unsaved_changes": toolkit.masked(draft.unsaved_changes()),
                    "complete": not toolkit.missing(self.ws, draft),
                }
            )
        last = next(
            (
                f"{a.get('section_type')}.{a.get('name')}"
                for n, a in reversed(self.calls)
                if n.startswith("section_") and a.get("name")
            ),
            None,
        )
        return {"drafts": drafts, "last_section": last}

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
        warnings: List[str] = []
        for draft in pending:  # checks that take time (an AI section is tried)
            refused, warned = await self.ws.toolkits[draft.section_type].preflight(self.ws, draft)
            errors += [f"{draft.label}: {e}" for e in refused]
            warnings += warned
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
                first=[d.key for d in pending if self.ws.toolkits[d.section_type].write_first(d)],
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
        notes = warnings + [
            note
            for draft in pending
            for note in self.ws.toolkits[draft.section_type].after_save(self.ws, draft)
        ]
        for note in notes:
            await self.ws.ui.say(note, kind="warning", markdown=True)
        tests = [d.key for d in pending if self.ws.toolkits[d.section_type].testable(self.ws, d)]
        self.testable.update(tests)
        for draft in pending:
            del self.ws.drafts[draft.key]
        try:
            await self.ws.load()
        except ConfigLoadError as e:
            await self.ws.ui.say(str(e), kind="error")
        result: Dict[str, Any] = {
            "ok": True,
            "saved": True,
            "sections": [d.label for d in pending],
        }
        result["note"] = (
            "Saved to the config file only; aimm configure starts no search. When the session "
            "ends, aimm itself tells the user how the change takes effect ("
            + how_to_run(self.ws.ui.monitor_running, monitoring_needs(self.ws))
            + "); do not repeat that."
        )
        if notes:
            result["shown_to_user"] = notes
        if tests:
            result["test_notification"] = {
                "sections": [{"section_type": t, "name": n} for t, n in tests],
                "note": (
                    "aimm can send a test message through what was just saved, now while the "
                    "user can still fix it: offer it with ask_user, in your own words, and say "
                    "that it sends a real message (metered channels such as UnitySVC SMS may "
                    "cost a little). Call test_notification for a section above only if the "
                    "user agrees."
                ),
            }
        return result

    async def test_notification(
        self: "ToolExecutor", section_type: str, name: str
    ) -> Dict[str, Any]:
        if (section_type, name) not in self.testable:
            offered = ", ".join(section_label(t, n) for t, n in sorted(self.testable))
            return {
                "ok": False,
                "errors": [
                    f"No test is offered for {section_label(section_type, name)}"
                    + (f"; only for {offered}." if offered else ".")
                    + " aimm offers one after a notification, or a user's channels, is saved."
                ],
            }
        return await self.ws.toolkits[section_type].send_test(self.ws, name)

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
            await self.ws.ui.say(message, kind="assistant")
        if pending:
            await self.ws.ui.say("Unsaved changes were discarded.", kind="warning")
        self.end(discarded=bool(pending))
        return {"ok": True}

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
        tools += _section_tools(self)
        if any(t in self.ws.toolkits for t in ("notification", "user")):

            async def test_notification(section_type: str, name: str) -> Dict[str, Any]:
                """Send a test message through a notification or user section just saved.

                Offered by `save` (its `test_notification` result) for the sections it lists;
                call it only after the user agreed. aimm sends one real message per channel,
                shows the result to the user and returns it (per channel: ok, or the error).

                Args:
                    section_type: "notification" or "user".
                    name: the section name, as listed by `save`.
                """
                return await self.call(
                    "test_notification", {"section_type": section_type, "name": name}
                )

            tools.append(test_notification)
        return tools

    async def call(self: "ToolExecutor", name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Run a tool by name (used by the model adapter and by tests).

        Every result carries ``session_state``, so the model always knows which sections it
        is working on, whatever it remembers of the conversation.
        """
        result = await self._call(name, args)
        if self.ws.drafts or name.startswith("section_"):
            result["session_state"] = self.session_state()
        return result

    async def _call(self: "ToolExecutor", name: str, args: Dict[str, Any]) -> Dict[str, Any]:
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
            section_type = str(args.get("section_type", ""))
            section_name = str(args.get("name", ""))
            if name == "test_notification":
                return await self.test_notification(section_type, section_name)
            if name == "section_guide":
                return await self.section_guide(section_type)
            if name == "section_show":
                return await self.section_show(section_type, section_name)
            if name == "section_check":
                return await self.section_check(section_type, section_name)
            if name == "section_update":
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


def _section_tools(executor: ToolExecutor) -> List[Callable[..., Awaitable[Dict[str, Any]]]]:
    """The generic section tools.

    The section type is an argument, so adding a section type adds no tools.
    """
    types = ", ".join(f'"{t}"' for t in executor.ws.toolkits)

    async def section_guide(section_type: str) -> Dict[str, Any]:
        return await executor.call("section_guide", {"section_type": section_type})

    async def section_show(section_type: str, name: str) -> Dict[str, Any]:
        return await executor.call("section_show", {"section_type": section_type, "name": name})

    async def section_update(
        section_type: str,
        name: str,
        values: str = "",
        unset: List[str] | None = None,
        request: str | None = None,
    ) -> Dict[str, Any]:
        return await executor.call(
            "section_update",
            {
                "section_type": section_type,
                "name": name,
                "values": values,
                "unset": unset,
                "request": request,
            },
        )

    async def section_check(section_type: str, name: str) -> Dict[str, Any]:
        return await executor.call("section_check", {"section_type": section_type, "name": name})

    section_guide.__doc__ = f"""Read how to configure a section type: its task playbook and fields.

    Read it before changing a section of that type.

    Args:
        section_type: one of {types}.
    """
    section_show.__doc__ = f"""Show a section: saved values, values in this session, unsaved
    changes, what is still required, and the names its fields may reference.

    Args:
        section_type: one of {types}.
        name: the section name, e.g. "facebook".
    """
    section_update.__doc__ = f"""Change the draft of a section; nothing is written until save.

    aimm validates the result and returns errors (the draft is then unchanged).

    Args:
        section_type: one of {types}.
        name: the section name.
        values: the fields to set, as a JSON object in a string, e.g.
            '{{"search_city": ["houston"], "radius": [30]}}'. Empty to set nothing.
        unset: fields to remove.
        request: one or two sentences: what the user wants from this section, in their terms.
    """
    section_check.__doc__ = f"""Check a section's draft: what is still required, validation
    errors, and unsaved changes.

    Args:
        section_type: one of {types}.
        name: the section name.
    """
    return [section_guide, section_show, section_update, section_check]
