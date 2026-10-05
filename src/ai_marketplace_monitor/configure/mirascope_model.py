"""The model adapter: Mirascope obtains tool calls; aimm runs them.

- An ``[ai.*]`` section becomes a Mirascope model. OpenAI-compatible services (UnitySVC,
  OpenAI, DeepSeek, Gemini, Ollama) are registered as the ``openai`` provider under a scope of
  their own with the section's ``base_url`` and key; Anthropic uses the ``anthropic`` provider.
- Tool calls run one at a time (``ask_user`` waits for the user), never concurrently.
- Each model call has a timeout and one retry on transient errors; errors are scrubbed of the
  key. Mirascope's providers accept no timeout, so aimm applies it.
- Assistant messages are re-sent without the provider's raw message: some gateways reject the
  extra fields (e.g. ``reasoning``) that would otherwise be echoed back.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List

from ..ai import AIBackend, AnthropicBackend
from .agent import ModelReply, ServiceError
from .ai_setup import scrub

TURN_TIMEOUT = 150  # seconds for one model call; slow reasoning models can take a minute

_TRANSIENT = ("TimeoutError", "ConnectionError", "ServerError", "APITimeoutError")


def model_id(backend: AIBackend) -> str:
    """Register the section's endpoint with Mirascope; return the model id to call."""
    from mirascope import llm

    config = backend.config
    model = str(config.model or getattr(backend, "default_model", ""))
    if "/" in model:
        raise ServiceError(
            f'The model "{model}" of [ai.{config.name}] contains "/", which aimm-configure '
            "cannot pass through; use another AI section."
        )
    if isinstance(backend, AnthropicBackend):
        # Mirascope's Anthropic provider only accepts the "anthropic/" model prefix
        llm.register_provider("anthropic", scope="anthropic/", api_key=config.api_key)
        return f"anthropic/{model}"
    scope = f"aimm-{config.name}/"
    base_url = getattr(config, "base_url", None) or getattr(backend, "base_url", None)
    llm.register_provider("openai", scope=scope, base_url=base_url, api_key=config.api_key)
    return f"{scope}{model}"


def _transient(e: BaseException) -> bool:
    status = getattr(e, "status_code", None)
    return (
        (isinstance(status, int) and status >= 500)
        or type(e).__name__ in _TRANSIENT
        or isinstance(e, asyncio.TimeoutError)
    )


class MirascopeModelSession:
    def __init__(
        self: "MirascopeModelSession",
        backend: AIBackend,
        tools: List[Callable[..., Awaitable[Dict[str, Any]]]],
        stop: Callable[[], bool],
        timeout: float = TURN_TIMEOUT,
    ) -> None:
        from mirascope import llm

        self._llm = llm
        self.model_id = model_id(backend)
        self.tools = [llm.tool(fn) for fn in tools]
        self.stop = stop
        self.timeout = timeout
        self.secret = backend.config.api_key
        self._last: Callable[[], Awaitable[Any]] | None = None

    async def _request(
        self: "MirascopeModelSession", make: Callable[[], Awaitable[Any]]
    ) -> ModelReply:
        self._last = make
        for attempt in range(2):
            try:
                response = await asyncio.wait_for(make(), self.timeout)
                break
            except Exception as e:
                if attempt == 0 and _transient(e):
                    continue
                detail = "timed out" if isinstance(e, asyncio.TimeoutError) else str(e)
                raise ServiceError(
                    f"The AI service failed: {scrub(detail, self.secret)[:300]}"
                ) from e
        return ModelReply(
            tool_calls=[(call.name, _args(call.args)) for call in response.tool_calls],
            text=response.text() or "",
            raw=response,
        )

    async def start(self: "MirascopeModelSession", system: str, user: str) -> ModelReply:
        model = self._llm.Model(self.model_id)
        messages = [self._llm.messages.system(system), self._llm.messages.user(user)]
        return await self._request(lambda: model.call_async(messages, tools=self.tools))

    async def run_tools(self: "MirascopeModelSession", reply: ModelReply) -> ModelReply:
        response = reply.raw
        outputs = []
        for call in response.tool_calls:  # in order: ask_user waits for the user
            outputs.append(await response.toolkit.execute(call))
            if self.stop():
                break
        if self.stop():
            return ModelReply()
        _strip_raw(response)
        return await self._request(lambda: response.resume(outputs))

    async def reply_text(
        self: "MirascopeModelSession", reply: ModelReply, text: str
    ) -> ModelReply:
        response = reply.raw
        _strip_raw(response)
        return await self._request(lambda: response.resume(text))

    async def retry(self: "MirascopeModelSession") -> ModelReply:
        assert self._last is not None
        return await self._request(self._last)


def _args(args: Any) -> Dict[str, Any]:
    if isinstance(args, dict):
        return args
    import json

    try:
        parsed = json.loads(args) if isinstance(args, str) else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _strip_raw(response: Any) -> None:
    for message in getattr(response, "messages", []):
        if getattr(message, "role", None) == "assistant":
            message.raw_message = None
