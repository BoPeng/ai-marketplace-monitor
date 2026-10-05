"""The Mirascope adapter, with Mirascope's registry and responses mocked (no network)."""

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from mirascope import llm

from ai_marketplace_monitor.ai import (
    AnthropicBackend,
    AnthropicConfig,
    OllamaBackend,
    OllamaConfig,
    OpenAIBackend,
    OpenAIConfig,
    UnitySVCBackend,
    UnitySVCConfig,
)
from ai_marketplace_monitor.configure import mirascope_model
from ai_marketplace_monitor.configure.agent import ModelReply, ServiceError
from ai_marketplace_monitor.configure.mirascope_model import MirascopeModelSession, model_id


@pytest.fixture
def registered(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        llm, "register_provider", lambda provider, **kw: calls.append({"provider": provider, **kw})
    )
    return calls


def test_openai_compatible_sections_get_their_own_scope(registered: List[Dict[str, Any]]) -> None:
    unitysvc = UnitySVCBackend(UnitySVCConfig(name="unitysvc", api_key="svcpass_k"))
    assert model_id(unitysvc) == "aimm-unitysvc/balanced"
    custom = UnitySVCBackend(
        UnitySVCConfig(
            name="qwen",
            api_key="svcpass_k",
            base_url="https://api.svcpass.com/qwencloud-dashscope/v1",
            model="qwen3.7-flash",
        )
    )
    assert model_id(custom) == "aimm-qwen/qwen3.7-flash"
    ollama = OllamaBackend(
        OllamaConfig(name="local", base_url="http://localhost:11434/v1", model="llama3")
    )
    assert model_id(ollama) == "aimm-local/llama3"
    openai = OpenAIBackend(OpenAIConfig(name="openai", api_key="sk-x"))
    assert model_id(openai) == "aimm-openai/gpt-4o"
    assert registered == [
        {
            "provider": "openai",
            "scope": "aimm-unitysvc/",
            "base_url": "https://api.svcpass.com/p/llm",
            "api_key": "svcpass_k",
        },
        {
            "provider": "openai",
            "scope": "aimm-qwen/",
            "base_url": "https://api.svcpass.com/qwencloud-dashscope/v1",
            "api_key": "svcpass_k",
        },
        {
            "provider": "openai",
            "scope": "aimm-local/",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
        },
        {"provider": "openai", "scope": "aimm-openai/", "base_url": None, "api_key": "sk-x"},
    ]


def test_anthropic_uses_the_standard_prefix(registered: List[Dict[str, Any]]) -> None:
    backend = AnthropicBackend(
        AnthropicConfig(name="claude", api_key="sk-ant-x", model="claude-sonnet-5-5")
    )
    assert model_id(backend) == "anthropic/claude-sonnet-5-5"
    assert registered == [{"provider": "anthropic", "scope": "anthropic/", "api_key": "sk-ant-x"}]


def test_model_names_with_a_slash_are_refused(registered: List[Dict[str, Any]]) -> None:
    backend = OpenAIBackend(OpenAIConfig(name="x", api_key="sk-x", model="org/model"))
    with pytest.raises(ServiceError, match="contains"):
        model_id(backend)


# --- the session, with fake Mirascope responses ------------------------------------------------
class FakeResponse:
    def __init__(self, calls: List[Any], text: str, log: List[str], nxt: Any = None) -> None:
        self.tool_calls = calls
        self._text = text
        self.log = log
        self.nxt = nxt
        self.messages = [SimpleNamespace(role="assistant", raw_message={"reasoning": "x"})]
        self.toolkit = SimpleNamespace(execute=self._execute)

    def text(self) -> str:
        return self._text

    async def _execute(self, call: Any) -> str:
        self.log.append(f"start {call.name}")
        await asyncio.sleep(0)
        self.log.append(f"end {call.name}")
        return f"out {call.name}"

    async def resume(self, content: Any) -> Any:
        self.log.append(f"resume {content!r} raw={self.messages[0].raw_message}")
        if isinstance(self.nxt, BaseException):
            raise self.nxt
        return self.nxt


def make_session(
    monkeypatch: pytest.MonkeyPatch, first: Any, stop: Any = lambda: False, timeout: float = 5
) -> MirascopeModelSession:
    monkeypatch.setattr(llm, "register_provider", lambda *a, **k: None)
    model = SimpleNamespace(call_async=lambda messages, tools: _resolve(first))
    monkeypatch.setattr(llm, "Model", lambda model_id: model)
    backend = UnitySVCBackend(UnitySVCConfig(name="unitysvc", api_key="svcpass_secretkey123"))
    return MirascopeModelSession(backend, [], stop=stop, timeout=timeout)


async def _resolve(value: Any) -> Any:
    if isinstance(value, BaseException):
        raise value
    if callable(value):
        return await value()
    return value


def call(name: str) -> Any:
    return SimpleNamespace(name=name, args={"x": 1})


async def test_tools_run_in_order_and_history_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    log: List[str] = []
    done = FakeResponse([], "bye", log)
    first = FakeResponse([call("ask_user"), call("marketplace_show")], "", log, nxt=done)
    session = make_session(monkeypatch, first)
    reply = await session.start("system", "hi")
    assert reply.tool_calls == [("ask_user", {"x": 1}), ("marketplace_show", {"x": 1})]
    nxt = await session.run_tools(reply)
    assert log == [
        "start ask_user",
        "end ask_user",
        "start marketplace_show",
        "end marketplace_show",
        "resume ['out ask_user', 'out marketplace_show'] raw=None",
    ]
    assert nxt.text == "bye" and nxt.tool_calls == []


async def test_stop_skips_the_next_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    log: List[str] = []
    first = FakeResponse([call("finish"), call("ask_user")], "", log)
    session = make_session(monkeypatch, first, stop=lambda: bool(log))
    assert await session.run_tools(await session.start("s", "u")) == ModelReply()
    assert log == ["start finish", "end finish"]


async def test_timeouts_and_errors_become_service_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow() -> Any:
        await asyncio.sleep(1)

    session = make_session(monkeypatch, slow, timeout=0.01)
    with pytest.raises(ServiceError, match="timed out"):
        await session.start("s", "u")

    class UnauthorizedError(Exception):
        status_code = 401

    session = make_session(monkeypatch, UnauthorizedError("bad key svcpass_secretkey123"))
    with pytest.raises(ServiceError) as e:
        await session.start("s", "u")
    assert "svcpass_secretkey123" not in str(e.value) and "bad key" in str(e.value)


async def test_transient_errors_are_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class GatewayError(Exception):
        status_code = 504

    attempts: List[int] = []

    async def flaky() -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            raise GatewayError("504")
        return FakeResponse([], "ok", [])

    session = make_session(monkeypatch, flaky)
    assert (await session.start("s", "u")).text == "ok" and len(attempts) == 2
    assert mirascope_model._transient(asyncio.TimeoutError())
