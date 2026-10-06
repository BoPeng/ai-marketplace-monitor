"""The generic agent loop: the LLM acts through tools until it finishes or the user quits.

``user ⇄ aimm ⇄ LLM``: the LLM talks to the user only through ``ask_user`` (or a plain-text
reply, which aimm shows and answers with the user's next message). The loop is independent of
the LLM library; a ``ModelSession`` adapter (``mirascope_model.py``, or a fake in tests) makes
the model calls and runs tool calls through the executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Protocol, Tuple

from .tools import Outcome, ToolExecutor, how_to_run, monitoring_needs
from .ui import SetupClosedError

# model calls in a row without the user saying anything before aimm makes the LLM ask
MAX_STEPS_WITHOUT_USER = 12
# model calls in one session
MAX_MODEL_CALLS = 60


class ServiceError(Exception):
    """The AI service failed (already scrubbed of secrets)."""


@dataclass
class ModelReply:
    tool_calls: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    text: str = ""
    raw: Any = None  # the adapter's own response object


class ModelSession(Protocol):
    # awaited right before each request to the model (the agent shows "Thinking...")
    on_call: Callable[[], Awaitable[None]] | None

    async def start(self: "ModelSession", system: str, user: str) -> ModelReply: ...

    async def run_tools(self: "ModelSession", reply: ModelReply) -> ModelReply:
        """Run the reply's tool calls in order (through the executor) and continue."""
        ...

    async def reply_text(self: "ModelSession", reply: ModelReply, text: str) -> ModelReply: ...

    async def retry(self: "ModelSession") -> ModelReply:
        """Repeat the last model request (after a service error)."""
        ...


async def run_agent(
    executor: ToolExecutor, model: ModelSession, system: str, opening: str
) -> Outcome:
    """Run one configure session; returns what happened. Ctrl-C raises ``SetupClosedError``."""
    ui = executor.ws.ui

    async def thinking() -> None:
        await ui.say("Thinking...", kind="progress")

    model.on_call = thinking  # shown right before each model request, never while tools run

    async def request(make: Callable[[], Awaitable[ModelReply]]) -> ModelReply | None:
        try:
            return await make()
        except ServiceError as e:
            await ui.say(str(e), kind="error")
            await ui.say(
                "If the AI service keeps failing, fix it with `aimm configure ai`.",
                kind="warning",
            )
            while True:
                answer = await executor.read_user("Press Enter to try again, or /quit to stop")
                if answer is None:
                    return None
                try:
                    return await model.retry()
                except ServiceError as again:
                    await ui.say(str(again), kind="error")

    reply = await request(lambda: model.start(system, opening))
    calls = 1
    while reply is not None and not executor.done:
        if calls >= MAX_MODEL_CALLS:
            await ui.say(f"Stopping after {calls} calls to the AI.", kind="warning")
            await _offer_save(executor)
            break
        if reply.tool_calls:
            executor.force_ask = executor.steps_without_user >= MAX_STEPS_WITHOUT_USER
            current = reply
            reply = await request(lambda c=current: model.run_tools(c))  # type: ignore[misc]
        else:
            if reply.text.strip():
                await ui.say(reply.text.strip(), kind="assistant")
            text = await executor.read_user()
            if text is None:
                break
            current = reply
            reply = await request(
                lambda c=current, t=text: model.reply_text(c, t)  # type: ignore[misc]
            )
        calls += 1
    if executor.saved:  # saving does not start a search; say so however the session ends
        missing = monitoring_needs(executor.ws)
        await ui.say(how_to_run(ui.monitor_running, missing), kind="success")
    if executor.closed:
        raise SetupClosedError
    if not executor.done:
        executor.end(discarded=bool(executor.ws.pending()))
    if executor.discarded:
        await ui.say("Nothing more was written.", kind="success")
    return executor.outcome


async def _offer_save(executor: ToolExecutor) -> None:
    """At the call limit: offer to save complete, valid unsaved changes (the user confirms)."""
    ws = executor.ws
    pending = ws.pending()
    complete = all(
        not ws.toolkits[d.section_type].missing(ws, d)
        and not ws.toolkits[d.section_type].validate(ws, d)
        for d in pending
    )
    if pending and complete:
        await executor.save("The changes made so far are complete; you can save them now.")
