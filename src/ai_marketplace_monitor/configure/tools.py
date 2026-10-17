"""The configure tools: everything the LLM can do, implemented by aimm.

The LLM changes nothing directly. It drafts sections with ``section_update`` (validated here),
talks to the user with ``ask_user``, and saves with ``save``, which shows the change and asks
the user before ``commit_sections`` writes only the drafted sections. Tools return dicts; errors
are returned, never raised, so the LLM can correct itself.

This module does not depend on any LLM library; ``tools_for_model()`` wraps the tools as plain
async functions with signatures and docstrings for the model adapter.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Sequence, Set, Tuple

from ..marketplaces.facebook.location import FacebookLocations, LocationLookupError
from ..shared_browser import shared_endpoint
from .history import explain_listing, find_listings
from .live import LiveBrowser
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
    # the cache that find_listings and explain_listing read (None: aimm's own; tests set one)
    history_cache: Any = None
    # opens Facebook pages in the monitor's browser (evaluate_listing, check_seller); made
    # when first used
    live: Any = None

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
        if self.live is not None:
            self.live.close()

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
        tried = [n for t, n in (d.key for d in pending) if t == "item"]
        if tried and await asyncio.to_thread(shared_endpoint) is not None:
            result["try_item"] = {
                "items": tried,
                "note": (
                    "aimm can run the search of what was just saved once, now, in the monitor's "
                    "browser, and list what it finds (search results only, no AI). Offer it "
                    "with ask_user, in your own words; call try_item only if the user agrees."
                ),
            }
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

    async def find_city(self: "ToolExecutor", place: str) -> Dict[str, Any]:
        """Look a place up in Facebook Marketplace's location search (no browser needed)."""
        if not place.strip():
            return {"ok": False, "errors": ["Give a city name, neighborhood or ZIP code."]}
        await self.ws.ui.say(f"Looking up {place} in Facebook Marketplace...")
        try:
            places = await asyncio.to_thread(FacebookLocations().find, place)
        except (LocationLookupError, OSError) as e:
            return {
                "ok": False,
                "errors": [
                    f"Facebook's location search did not answer ({e}). Ask the user for the "
                    "URL of a Marketplace search instead, as the search_city guide says."
                ],
            }
        if not places:
            return {
                "ok": False,
                "errors": [
                    f"Facebook found no place for {place!r}. Check the spelling, or try the full "
                    "state or country name, or a ZIP code."
                ],
            }
        found = [
            {
                "place": p.label,
                "detail": p.detail,
                # each marketplace type's search_city for the place
                "facebook": p.code,
                "offerup": f"{p.latitude:.4f},{p.longitude:.4f}",
            }
            for p in places
        ]
        self.ws.found_city_codes |= {v for f in found for v in (f["facebook"], f["offerup"])}
        return {
            "ok": True,
            "places": found,
            "note": (
                "Facebook's matches for what the user typed, best first (at most 10). Confirm "
                "the place with the user before saving: if one clearly fits, ask whether it is "
                "right; if several could be meant, offer them by `place` (e.g. Los Angeles, "
                "California or Los Angeles in Mexico); if the user's place is not listed, call "
                "find_city again with its state or country added. Then set search_city to the "
                "value for the section's marketplace type: `facebook` for a Facebook section, "
                "`offerup` for an OfferUp one (its coordinates; a ZIP code the user gave works "
                "too); for an item searched in both, a table: "
                '{ facebook = "<facebook>", offerup = "<offerup>" }. Set city_name to its '
                "`place`. Places with the same `facebook` value are the same Marketplace location."
            ),
        }

    # --- what aimm found (read from the cache) --------------------------------------------
    async def find_listings(self: "ToolExecutor", args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            days = float(args.get("days") or 0)
            min_rating = int(args.get("min_rating") or 0)
            limit = int(args.get("limit") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "errors": ["days, min_rating and limit must be numbers."]}
        return await asyncio.to_thread(
            find_listings,
            text=str(args.get("text") or ""),
            item=str(args.get("item") or ""),
            stage=str(args.get("stage") or ""),
            days=days,
            min_rating=min_rating,
            sort=str(args.get("sort") or "time"),
            limit=limit,
            local_cache=self.history_cache,
        )

    async def explain_listing(self: "ToolExecutor", listing: str) -> Dict[str, Any]:
        return await asyncio.to_thread(explain_listing, listing, local_cache=self.history_cache)

    # --- Facebook pages, in the monitor's browser -------------------------------------------
    def _live(self: "ToolExecutor") -> Any:
        if self.live is None:
            self.live = LiveBrowser(self.ws.files)
        return self.live

    async def evaluate_listing(
        self: "ToolExecutor", listing: str, item: str, refresh: bool = False
    ) -> Dict[str, Any]:
        await self.ws.ui.say("Checking the listing and asking the AI...")
        return await self._live().evaluate_listing(listing, item, refresh)

    async def check_seller(
        self: "ToolExecutor", seller: str, refresh: bool = False
    ) -> Dict[str, Any]:
        await self.ws.ui.say("Checking the seller...")
        return await self._live().check_seller(seller, refresh)

    async def try_item(self: "ToolExecutor", item: str) -> Dict[str, Any]:
        item = item.strip()
        if not item:
            saved = list(self.ws.user_cfg.get("item", {}))
            if len(saved) != 1:
                return {
                    "ok": False,
                    "errors": [
                        "Which item? "
                        + (f"Items: {', '.join(saved)}." if saved else "No item is saved.")
                    ],
                }
            item = saved[0]
        if (
            self.only is not None
            and ("item", item) not in self.only
            and ("item", "*") not in self.only
        ):
            allowed = ", ".join(section_label(t, n) for t, n in sorted(self.only))
            return {"ok": False, "errors": [f"This session works on {allowed} only."]}
        draft = self.ws.drafts.get(("item", item))
        if draft is not None and draft.unsaved_changes():
            return {
                "ok": False,
                "errors": [
                    f"{section_label('item', item)} has unsaved changes: the search runs what is "
                    "saved. Save it first."
                ],
            }
        await self.ws.ui.say(f"Running the search of {section_label('item', item)} once...")
        return await self._live().try_item(item)

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

            async def find_listings(
                text: str = "",
                item: str = "",
                stage: str = "",
                days: float = 0,
                min_rating: int = 0,
                sort: str = "time",
                limit: int = 20,
            ) -> Dict[str, Any]:
                """List the listings aimm's searches found and what it decided about each.

                Read from aimm's records (no browser): each listing with its item, stage
                (excluded, rejected or notified), AI rating, title, price, location, when it
                was decided, URL and a short reason. Also the number per stage. Records are
                kept `evaluation_history_days` (30 days by default).

                Args:
                    text: words to find in the title, seller, location, price, reason or AI
                        comment, e.g. "hero 12". Empty for all.
                    item: an item name, e.g. "gopro". Empty for all items.
                    stage: "excluded", "rejected" or "notified". Empty for all.
                    days: only listings decided in the last this many days; 0 for all.
                    min_rating: only listings the AI rated at least this (1-5); 0 for all.
                    sort: "time" (newest first) or "rating" (best first).
                    limit: how many listings to return (at most 50).
                """
                return await self.call(
                    "find_listings",
                    {
                        "text": text,
                        "item": item,
                        "stage": stage,
                        "days": days,
                        "min_rating": min_rating,
                        "sort": sort,
                        "limit": limit,
                    },
                )

            async def explain_listing(listing: str) -> Dict[str, Any]:
                """Explain what aimm knows and decided about one listing, from its records.

                Returns the decision for each item that found it (stage, AI rating, the reason
                or the AI's comment), the listing's details and description as aimm read them,
                its price and status history, and its seller (summary and warning signs). No
                browser: a listing aimm never found is not known.

                Args:
                    listing: the listing's Facebook Marketplace URL or its id.
                """
                return await self.call("explain_listing", {"listing": listing})

            async def evaluate_listing(
                listing: str, item: str = "", refresh: bool = False
            ) -> Dict[str, Any]:
                """Rate one listing (Facebook or OfferUp) for one [item.*], as its search would.

                One listing, one existing item: it does not search. aimm reads the listing and
                its seller as a search would, says whether the search would exclude it before
                the AI (keywords and other filters), and asks the item's AI to rate it. A
                listing aimm read before is rated from its cache. Otherwise: an OfferUp listing
                is read directly; a Facebook listing is opened in the monitor's browser, which
                takes up to a minute or two and needs the monitor running on this computer,
                logged in to Facebook (if not, it says so). Nothing is recorded and no one is
                notified.

                Args:
                    listing: the listing's URL (Facebook Marketplace or OfferUp) or its id.
                    item: the item to rate it for, e.g. "gopro"; may be empty if there is only
                        one item.
                    refresh: true only when the user asks for a fresh look (e.g. the price
                        changed): open the page again and ask the AI again.
                """
                return await self.call(
                    "evaluate_listing", {"listing": listing, "item": item, "refresh": refresh}
                )

            async def check_seller(seller: str, refresh: bool = False) -> Dict[str, Any]:
                """Is this seller legit? Their profile (Facebook or OfferUp) and warning signs.

                Returns when they joined, their rating and number of ratings, listings sold
                (and active, on Facebook), what buyers say, and warning signs. A profile read
                in the last month comes from aimm's cache; otherwise an OfferUp profile is read
                directly, and a Facebook profile is opened in the monitor's browser, which
                needs the monitor running on this computer, as evaluate_listing does.

                Args:
                    seller: the seller's profile URL (Facebook /marketplace/profile/<id>,
                        OfferUp offerup.com/p/<id>), their id, or the URL of one of their
                        listings.
                    refresh: true only when the user asks for a fresh look: open the profile
                        again.
                """
                return await self.call("check_seller", {"seller": seller, "refresh": refresh})

            tools += [
                list_sections,
                find_listings,
                explain_listing,
                evaluate_listing,
                check_seller,
            ]
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
        if "item" in self.ws.toolkits:

            async def try_item(item: str) -> Dict[str, Any]:
                """Run a saved item's search once, now, and list what it finds.

                aimm runs the item's searches (its search phrases in its cities, with its price,
                radius and other options, up to 4 pages in all) in each marketplace it is
                searched in, and applies the filters that work on search results (title,
                location, price). It opens no listing page and asks no AI, so it is quick and
                free; rate listings the user picks with evaluate_listing. OfferUp is searched
                directly; Facebook needs the monitor running on this computer, logged in to
                Facebook (if not, it says so). Runs only what is saved: save the item first.
                Nothing is recorded and no one is notified.

                Args:
                    item: the item's name, e.g. "gopro".
                """
                return await self.call("try_item", {"item": item})

            tools.append(try_item)
        if any(t in self.ws.toolkits for t in ("marketplace", "item", "region")):

            async def find_city(place: str) -> Dict[str, Any]:
                """Find the `search_city` code of a place the user names, from Facebook.

                aimm asks Facebook Marketplace's location search, as its location dialog does
                (no browser or Facebook account needed, and nothing is changed). It returns
                Facebook's matching places, best first (at most 10), each labelled with its
                region and with its `search_city` code: confirm with the user which one is
                meant.

                Args:
                    place: what the user said, spelled correctly: a city (with its state or
                        country if given), a neighborhood or a ZIP code, e.g. "Los Angeles",
                        "San Diego, CA" or "77494".
                """
                return await self.call("find_city", {"place": place})

            tools.append(find_city)
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
            if name == "find_city":
                return await self.find_city(str(args.get("place", "")))
            if name == "find_listings":
                return await self.find_listings(args)
            if name == "explain_listing":
                return await self.explain_listing(str(args.get("listing", "")))
            if name == "evaluate_listing":
                return await self.evaluate_listing(
                    str(args.get("listing", "")),
                    str(args.get("item", "") or ""),
                    args.get("refresh") is True,
                )
            if name == "try_item":
                return await self.try_item(str(args.get("item", "")))
            if name == "check_seller":
                return await self.check_seller(
                    str(args.get("seller", "")), args.get("refresh") is True
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

    # `values`, `unset` and `request` keep non-None defaults so every parameter schema
    # stays a single type: the model adapter sends the tools with strict schemas, and
    # strict backends reject a parameter that mixes types (e.g. a string and null)
    async def section_update(
        section_type: str,
        name: str,
        values: str = "",
        unset: Tuple[str, ...] = (),
        request: str = "",
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
        unset: fields to remove, e.g. ["radius"]. Empty to remove nothing.
        request: one or two sentences: what the user wants from this section, in their
            terms. Empty to leave the section's request unchanged.
    """
    section_check.__doc__ = f"""Check a section's draft: what is still required, validation
    errors, and unsaved changes.

    Args:
        section_type: one of {types}.
        name: the section name.
    """
    return [section_guide, section_show, section_update, section_check]
