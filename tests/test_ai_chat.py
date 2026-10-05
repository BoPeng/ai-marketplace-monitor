from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor.ai import (
    AnthropicBackend,
    AnthropicConfig,
    UnitySVCBackend,
    UnitySVCConfig,
)

MESSAGES = [
    {"role": "system", "content": "rules"},
    {"role": "user", "content": "hello"},
]


def openai_reply(text: str) -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def unitysvc(client: Any) -> UnitySVCBackend:
    backend = UnitySVCBackend(UnitySVCConfig(name="unitysvc", api_key="svcpass_x"))
    backend.client = client
    return backend


def test_openai_chat_sends_json_mode() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = openai_reply('{"ok": true}')

    assert unitysvc(client).chat(MESSAGES, json_mode=True) == '{"ok": true}'
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "balanced"
    assert kwargs["messages"] == MESSAGES
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    "error, dropped, added",
    [
        ("response_format is not supported", "response_format", None),
        ("use max_completion_tokens instead", "max_tokens", "max_completion_tokens"),
    ],
)
def test_openai_chat_retries_without_unsupported_options(
    error: str, dropped: str, added: str | None
) -> None:
    calls: List[Dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise RuntimeError(error)
        return openai_reply("{}")

    client = MagicMock()
    client.chat.completions.create.side_effect = create
    assert unitysvc(client).chat(MESSAGES, json_mode=True) == "{}"
    assert dropped in calls[0] and dropped not in calls[1]
    if added:
        assert calls[1][added] == 2048


def test_openai_chat_raises_other_errors() -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("401 unauthorized")
    with pytest.raises(RuntimeError, match="401"):
        unitysvc(client).chat(MESSAGES)


def test_anthropic_chat_moves_system_messages() -> None:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text='{"a": '), SimpleNamespace(text="1}")]
    )
    backend = AnthropicBackend(AnthropicConfig(name="anthropic", api_key="sk-ant"))
    backend.client = client

    assert backend.chat(MESSAGES, json_mode=True) == '{"a": 1}'
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["system"] == "rules"
    assert kwargs["messages"] == [{"role": "user", "content": "hello"}]


def test_chat_timeout_disables_client_retries() -> None:
    client = MagicMock()
    bounded = client.with_options.return_value
    bounded.chat.completions.create.return_value = openai_reply("{}")

    assert unitysvc(client).chat(MESSAGES, timeout=30) == "{}"
    client.with_options.assert_called_once_with(timeout=30, max_retries=0)
    client.chat.completions.create.assert_not_called()


def test_openai_chat_applies_both_fallbacks() -> None:
    calls: List[Dict[str, Any]] = []
    errors = ["response_format is not supported", "use max_completion_tokens instead"]

    def create(**kwargs: Any) -> Any:
        calls.append(dict(kwargs))
        if errors:
            raise RuntimeError(errors.pop(0))
        return openai_reply("{}")

    client = MagicMock()
    client.chat.completions.create.side_effect = create
    assert unitysvc(client).chat(MESSAGES, json_mode=True) == "{}"
    assert len(calls) == 3
    assert "response_format" not in calls[2] and calls[2]["max_completion_tokens"] == 2048
