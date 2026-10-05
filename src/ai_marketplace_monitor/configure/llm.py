"""One structured LLM turn: build the prompt, parse the JSON reply, validate, retry."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Dict, List

from .ai_setup import run_in_daemon_thread, scrub
from .sections import SectionDraft, TurnError, TurnResult, is_reference

if TYPE_CHECKING:
    from .sections import BuilderContext, SectionBuilder

MAX_RETRIES = 2
# seconds for one AI reply; slow reasoning models can take a minute
TURN_TIMEOUT = 150
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class Exchange:
    role: str  # "assistant" (the LLM's message) or "user"
    text: str


def parse_reply(text: str) -> Dict[str, Any]:
    """The JSON object in an LLM reply; tolerates code fences and text around it."""
    candidates = [text.strip(), *(m.strip() for m in _FENCE.findall(text))]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("The reply is not a JSON object.")


def build_messages(
    builder: "SectionBuilder",
    ctx: "BuilderContext",
    draft: SectionDraft,
    history: List[Exchange],
    feedback: List[str],
) -> List[Dict[str, str]]:
    playbook = ctx.playbooks[builder.playbook]
    system = "\n\n".join(
        [
            ctx.playbooks["AGENT"].text(),
            f"# Task: configure a [{builder.section_type}] section\n\n{playbook.text()}",
            f"# Field table\n\n{builder.guide_table()}",
        ]
    )
    situation = {
        "section": f"{builder.section_type}.{draft.name}",
        "new": draft.is_new,
        "request": draft.request,
        "values": builder.masked(draft.values),
        "items_with_their_own_values": draft.item_overrides,
        "apply_to_all_items": sorted(draft.all_items),
        "still_required": builder.missing(ctx, draft),
        "context": builder.context(ctx, draft),
    }
    lines = [f"# Situation\n\n```json\n{json.dumps(situation, indent=2, default=str)}\n```"]
    if history:
        convo = "\n".join(
            f"{'You' if x.role == 'assistant' else 'User'}: {x.text}" for x in history
        )
        lines.append(f"# Conversation so far\n\n{convo}")
    else:
        lines.append("# Conversation so far\n\n(none yet: open the conversation)")
    if feedback:
        lines.append("# Notes from aimm\n\n" + "\n".join(f"- {f}" for f in feedback))
    lines.append("Reply with one JSON object as described.")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(lines)},
    ]


def merge_reply(
    builder: "SectionBuilder", draft: SectionDraft, reply: Dict[str, Any]
) -> tuple[SectionDraft, List[str]]:
    """Apply a parsed reply to a copy of the draft; return it with any problems found."""
    problems: List[str] = []
    new = draft.copy()
    names = set(builder.field_names())
    values = reply.get("values") or {}
    unset = reply.get("unset") or []
    if not isinstance(values, dict) or not isinstance(unset, list):
        return draft, ["`values` must be an object and `unset` a list."]
    for key, value in values.items():
        if key not in names:
            problems.append(f"`{key}` is not a field of this section.")
        elif builder.guide(key).secret and not is_reference(value):
            problems.append(f"`{key}` is secret: only a ${{VAR}} reference may be set.")
        else:
            new.values[key] = value
    for key in unset:
        new.values.pop(key, None)
    all_items = reply.get("apply_to_all_items") or []
    if isinstance(all_items, list):
        new.all_items |= {k for k in all_items if k in names}
    if isinstance(reply.get("request"), str) and reply["request"].strip():
        new.request = reply["request"].strip()
    return new, problems


def _transient(e: Exception) -> bool:
    """Timeouts, connection errors and 5xx answers, which are worth one more try."""
    status = getattr(e, "status_code", None)
    name = type(e).__name__
    return (isinstance(status, int) and status >= 500) or "Timeout" in name or "Connection" in name


async def _ask(ctx: "BuilderContext", messages: List[Dict[str, str]]) -> str:
    call = partial(ctx.ai.chat, messages, json_mode=True, timeout=TURN_TIMEOUT)
    for attempt in range(2):
        try:
            return await run_in_daemon_thread(call)
        except Exception as e:
            if attempt == 0 and _transient(e):
                continue
            secret = getattr(ctx.ai.config, "api_key", None)
            raise TurnError(
                f"The AI service failed: {scrub(str(e), secret)[:300]}", service=True
            ) from e
    raise AssertionError("unreachable")  # pragma: no cover


async def run_turn(
    builder: "SectionBuilder",
    ctx: "BuilderContext",
    draft: SectionDraft,
    history: List[Exchange],
    feedback: List[str],
) -> TurnResult:
    """Ask the LLM for its next message and section values; retry on invalid replies."""
    errors: List[str] = []
    for _attempt in range(MAX_RETRIES + 1):
        notes = list(feedback) + [f"Your previous reply was not usable: {e}" for e in errors]
        messages = build_messages(builder, ctx, draft, history, notes)
        text = await _ask(ctx, messages)
        try:
            reply = parse_reply(text)
        except ValueError as e:
            errors = [str(e)]
            continue
        candidate, errors = merge_reply(builder, draft, reply)
        errors += builder.validate(ctx, candidate) if not errors else []
        if errors:
            continue
        message = reply.get("message")
        return TurnResult(
            draft=candidate,
            message=message.strip() if isinstance(message, str) and message.strip() else "",
            complete=reply.get("complete") is True,
        )
    raise TurnError(
        "The AI couldn't turn that into a valid section"
        + (f" ({'; '.join(errors)[:300]})" if errors else "")
        + ". Please try saying it differently."
    )
