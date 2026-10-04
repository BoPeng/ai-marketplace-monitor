from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor import config as config_module
from ai_marketplace_monitor.ai import (
    AnthropicBackend,
    AnthropicConfig,
    UnitySVCBackend,
    UnitySVCConfig,
)
from ai_marketplace_monitor.config import resolve_config_files


def test_resolve_without_default_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_module, "amm_home", tmp_path / "home")
    given = tmp_path / "a.toml"
    given.write_text("")
    assert resolve_config_files([given]) == [given.resolve()]


def test_resolve_puts_default_file_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text("")
    monkeypatch.setattr(config_module, "amm_home", home)
    given = tmp_path / "a.toml"
    given.write_text("")
    assert resolve_config_files([given]) == [home / "config.toml", given.resolve()]
    assert resolve_config_files(None) == [home / "config.toml"]


def test_resolve_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        resolve_config_files([tmp_path / "missing.toml"])


def test_openai_compatible_chat_uses_default_model() -> None:
    backend = UnitySVCBackend(UnitySVCConfig(name="unitysvc", api_key="svcpass_test"))
    backend.client = MagicMock()
    reply = SimpleNamespace(message=SimpleNamespace(content="hello"))
    backend.client.chat.completions.create.return_value = SimpleNamespace(choices=[reply])
    messages = [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}]
    assert backend.chat(messages) == "hello"
    backend.client.chat.completions.create.assert_called_once_with(
        model="balanced", messages=messages
    )


def test_anthropic_chat_moves_system_messages() -> None:
    backend = AnthropicBackend(AnthropicConfig(name="anthropic", api_key="sk-ant-test"))
    backend.client = MagicMock()
    backend.client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hel"), SimpleNamespace(type="text", text="lo")]
    )
    messages = [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}]
    assert backend.chat(messages) == "hello"
    kwargs = backend.client.messages.create.call_args.kwargs
    assert kwargs["system"] == "be nice"
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert kwargs["max_tokens"] == 4096
    assert kwargs["model"] == AnthropicBackend.default_model
