from pathlib import Path
from typing import Any, List

import pytest
from typer.testing import CliRunner

from ai_marketplace_monitor.configure import cli, flow
from ai_marketplace_monitor.configure.ui import ScriptedSetupUI

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

    monkeypatch.setattr(flow, "configure_ai", fake_configure_ai)

    assert await flow.configure_front_door(ScriptedSetupUI(["quit"]), files) == 0
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

    monkeypatch.setattr(flow, "configure_ai", fake_configure_ai)

    assert await flow.configure_front_door(ScriptedSetupUI(["ai", "quit"]), []) == 0
    assert calls == [([], None), ([], None)]


async def test_configure_section_item_requires_usable_ai() -> None:
    ui = ScriptedSetupUI([])

    assert await flow.configure_section(ui, [], "item.gopro") == 1
    assert "Configure a working AI service first" in ui.said("error")[0]


async def test_configure_section_item_is_reserved_after_ai_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_require_usable_ai(ui: Any, config_files: List[Path]) -> bool:
        return True

    monkeypatch.setattr(flow, "require_usable_ai", fake_require_usable_ai)
    ui = ScriptedSetupUI([])

    assert await flow.configure_section(ui, [], "item.gopro") == 1
    assert "not implemented yet" in ui.said("error")[0]


def test_configure_cli_dispatches_to_front_door(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[List[Path]] = []
    config = Path("custom.toml")

    async def fake_configure_front_door(ui: Any, files: List[Path]) -> int:
        calls.append(files)
        return 0

    monkeypatch.setattr(cli, "configure_front_door", fake_configure_front_door)
    monkeypatch.setattr(cli, "ConsoleSetupUI", lambda: ScriptedSetupUI([]))
    monkeypatch.setattr(cli, "resolve_config_files", lambda files: files)

    result = runner.invoke(cli.app, ["--config-file", str(config)])

    assert result.exit_code == 0
    assert calls == [[config]]


def test_configure_cli_dispatches_explicit_section(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[tuple[List[Path], str]] = []
    config = Path("custom.toml")

    async def fake_configure_section(ui: Any, files: List[Path], section: str) -> int:
        calls.append((files, section))
        return 0

    monkeypatch.setattr(cli, "configure_section", fake_configure_section)
    monkeypatch.setattr(cli, "ConsoleSetupUI", lambda: ScriptedSetupUI([]))
    monkeypatch.setattr(cli, "resolve_config_files", lambda files: files)

    result = runner.invoke(cli.app, ["--config-file", str(config), "ai.unitysvc"])

    assert result.exit_code == 0
    assert calls == [([config], "ai.unitysvc")]


def test_configure_cli_rejects_unimplemented_sections() -> None:
    result = runner.invoke(cli.app, ["user.me"])

    assert result.exit_code == 1
    assert "Only 'ai', 'ai.<name>', 'item', and 'item.<name>'" in result.output


def test_configure_cli_needs_terminal() -> None:
    result = runner.invoke(cli.app, [])

    assert result.exit_code == 1
    assert "interactive terminal" in result.output


def test_resolve_config_files_puts_default_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_marketplace_monitor import config

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text("")
    given = tmp_path / "extra.toml"
    given.write_text("")
    monkeypatch.setattr(config, "amm_home", home)

    assert config.resolve_config_files([given]) == [home / "config.toml", given.resolve()]
    with pytest.raises(FileNotFoundError, match="not found"):
        config.resolve_config_files([tmp_path / "missing.toml"])


def test_ctrl_c_during_setup_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    async def interrupted(ui: Any, files: List[Path]) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "configure_front_door", interrupted)
    monkeypatch.setattr(cli, "ConsoleSetupUI", lambda: ScriptedSetupUI([]))
    monkeypatch.setattr(cli, "resolve_config_files", lambda files: [])

    result = runner.invoke(cli.app, [])

    assert result.exit_code == 0
    assert "Cancelled." in result.output


@pytest.mark.parametrize("first_ok, checked", [(True, ["first"]), (False, ["first", "second"])])
async def test_require_usable_ai_checks_the_default_first(
    monkeypatch: pytest.MonkeyPatch, first_ok: bool, checked: List[str]
) -> None:
    from ai_marketplace_monitor.configure.ai_setup import AISection, ProbeResult

    sections = [AISection("first", {}, []), AISection("second", {}, [])]
    monkeypatch.setattr(flow, "load_ai_sections", lambda files: sections)
    seen: List[str] = []

    async def probe(batch: List[AISection]) -> List[ProbeResult]:
        seen.extend(s.name for s in batch)
        ok = first_ok or batch[0].name == "second"
        return [ProbeResult(ok, "request", "m", "" if ok else "broken")]

    monkeypatch.setattr(flow, "probe_sections", probe)
    ui = ScriptedSetupUI([])
    assert await flow.require_usable_ai(ui, []) is True
    assert seen == checked
    fallback = any("Your default AI [ai.first] does not work" in m for m in ui.said("warning"))
    assert fallback is not first_ok
