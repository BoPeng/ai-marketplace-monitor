from pathlib import Path
from typing import Any, List

import pytest
from typer.testing import CliRunner

from ai_marketplace_monitor import ai_setup, configure, configure_cli

runner = CliRunner()


async def test_configure_front_door_runs_ai_then_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: List[tuple[List[Path], str | None]] = []
    files = [Path("custom.toml")]

    async def fake_configure_ai(
        ui: Any,
        config_files: List[Path],
        *,
        section_name: str | None = None,
        home: Path | None = None,
    ) -> int:
        calls.append((config_files, section_name))
        return 0

    monkeypatch.setattr(configure, "configure_ai", fake_configure_ai)

    assert await configure.configure_front_door(ai_setup.ScriptedSetupUI(["quit"]), files) == 0
    assert calls == [(files, None)]


async def test_configure_front_door_can_call_ai_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: List[tuple[List[Path], str | None]] = []

    async def fake_configure_ai(
        ui: Any,
        config_files: List[Path],
        *,
        section_name: str | None = None,
        home: Path | None = None,
    ) -> int:
        calls.append((config_files, section_name))
        return 0

    monkeypatch.setattr(configure, "configure_ai", fake_configure_ai)

    assert await configure.configure_front_door(ai_setup.ScriptedSetupUI(["ai", "quit"]), []) == 0
    assert calls == [([], None), ([], None)]


async def test_configure_section_item_requires_usable_ai() -> None:
    ui = ai_setup.ScriptedSetupUI([])

    assert await configure.configure_section(ui, [], "item.gopro") == 1
    assert "Configure a working AI service first" in ui.said("error")[0]


async def test_configure_section_item_is_reserved_after_ai_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_require_usable_ai(ui: Any, config_files: List[Path]) -> bool:
        return True

    monkeypatch.setattr(configure, "require_usable_ai", fake_require_usable_ai)
    ui = ai_setup.ScriptedSetupUI([])

    assert await configure.configure_section(ui, [], "item.gopro") == 1
    assert "not implemented yet" in ui.said("error")[0]


def test_configure_cli_dispatches_to_front_door(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[List[Path]] = []
    config = Path("custom.toml")

    async def fake_configure_front_door(ui: Any, files: List[Path]) -> int:
        calls.append(files)
        return 0

    monkeypatch.setattr(configure_cli, "configure_front_door", fake_configure_front_door)
    monkeypatch.setattr(configure_cli, "ConsoleSetupUI", lambda: ai_setup.ScriptedSetupUI([]))
    monkeypatch.setattr(configure_cli, "resolve_setup_config_files", lambda files: files)

    result = runner.invoke(configure_cli.app, ["--config-file", str(config)])

    assert result.exit_code == 0
    assert calls == [[config]]


def test_configure_cli_dispatches_explicit_section(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[tuple[List[Path], str]] = []
    config = Path("custom.toml")

    async def fake_configure_section(ui: Any, files: List[Path], section: str) -> int:
        calls.append((files, section))
        return 0

    monkeypatch.setattr(configure_cli, "configure_section", fake_configure_section)
    monkeypatch.setattr(configure_cli, "ConsoleSetupUI", lambda: ai_setup.ScriptedSetupUI([]))
    monkeypatch.setattr(configure_cli, "resolve_setup_config_files", lambda files: files)

    result = runner.invoke(configure_cli.app, ["--config-file", str(config), "ai.unitysvc"])

    assert result.exit_code == 0
    assert calls == [([config], "ai.unitysvc")]


def test_configure_cli_rejects_unimplemented_sections() -> None:
    result = runner.invoke(configure_cli.app, ["user.me"])

    assert result.exit_code == 1
    assert "Only 'ai', 'ai.<name>', 'item', and 'item.<name>'" in result.output


def test_configure_cli_needs_terminal() -> None:
    result = runner.invoke(configure_cli.app, [])

    assert result.exit_code == 1
    assert "interactive terminal" in result.output
