from pathlib import Path
from typing import Any, List

import pytest
from typer.testing import CliRunner

from ai_marketplace_monitor import ai_setup, configure_cli

runner = CliRunner()


def test_configure_cli_dispatches_to_ai_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[tuple[List[Path], str | None]] = []
    config = Path("custom.toml")

    async def fake_configure_ai(
        ui: Any, files: List[Path], *, section_name: str | None = None
    ) -> int:
        calls.append((files, section_name))
        return 0

    monkeypatch.setattr(configure_cli, "configure_ai", fake_configure_ai)
    monkeypatch.setattr(configure_cli, "ConsoleSetupUI", lambda: ai_setup.ScriptedSetupUI([]))
    monkeypatch.setattr(configure_cli, "resolve_setup_config_files", lambda files: files)

    result = runner.invoke(configure_cli.app, ["--config-file", str(config), "ai.unitysvc"])

    assert result.exit_code == 0
    assert calls == [([config], "unitysvc")]


def test_configure_cli_rejects_unimplemented_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(configure_cli, "ConsoleSetupUI", lambda: ai_setup.ScriptedSetupUI([]))

    result = runner.invoke(configure_cli.app, ["item.example"])

    assert result.exit_code == 1
    assert "Only 'ai' and 'ai.<name>' are supported" in result.output


def test_configure_cli_needs_terminal() -> None:
    result = runner.invoke(configure_cli.app, [])

    assert result.exit_code == 1
    assert "interactive terminal" in result.output
