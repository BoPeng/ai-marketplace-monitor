from pathlib import Path
from typing import Any, Dict, List

import pytest
from typer.testing import CliRunner

from ai_marketplace_monitor.configure import cli, flow
from ai_marketplace_monitor.configure.ui import ScriptedSetupUI

runner = CliRunner()


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
    assert "Only 'ai', 'ai.<name>', 'marketplace', 'marketplace.<name>'" in result.output


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


@pytest.mark.parametrize("address", ["marketplace", "marketplace.facebook", "item", "item.bike"])
def test_marketplace_and_item_addresses_are_valid(address: str) -> None:
    flow.validate_section_address(address)


def test_empty_section_name_is_rejected() -> None:
    with pytest.raises(flow.ConfigureAddressError):
        flow.validate_section_address("marketplace.")


def use_fake_model(monkeypatch: pytest.MonkeyPatch, steps: List[Any]) -> List[Any]:
    """Replace the Mirascope adapter with a scripted model; returns the models created."""
    from ai_marketplace_monitor.configure import mirascope_model
    from tests.configure_util import FakeModel

    made: List[Any] = []

    def factory(backend: Any, tools: Any, stop: Any) -> Any:
        made.append(FakeModel(steps).bind(tools, stop))
        made[-1].backend = backend
        return made[-1]

    monkeypatch.setattr(mirascope_model, "MirascopeModelSession", factory)
    monkeypatch.setattr(llm_registry(), "register_provider", lambda *a, **k: None)
    return made


def llm_registry() -> Any:
    from mirascope import llm

    return llm


def read(path: Path) -> Dict[str, Any]:
    import sys

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    return tomllib.loads(path.read_text())


async def test_configure_marketplace_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.configure_util import BASE

    config = tmp_path / "config.toml"
    config.write_text(BASE, encoding="utf-8")
    made = use_fake_model(
        monkeypatch,
        [
            [("section_show", {"section_type": "marketplace", "name": "home"})],
            [
                (
                    "section_update",
                    {
                        "section_type": "marketplace",
                        "name": "home",
                        "values": {"search_city": ["austin"], "radius": [25]},
                        "request": "Austin within 25 miles.",
                    },
                )
            ],
            [("save", {"message": "Saving Austin, 25 miles."})],
            [("finish", {"message": "Done."})],
        ],
    )
    ui = ScriptedSetupUI(["yes"])
    assert await flow.configure_section(ui, [config], "marketplace.home", home=tmp_path) == 0
    assert read(config)["marketplace"]["home"] == {
        "search_city": ["austin"],
        "radius": [25],
        "request": "Austin within 25 miles.",
    }
    assert "[marketplace.home] is new." in ui.said()
    assert "Using [ai.unitysvc]." in ui.said("progress")  # the default AI, not probed
    assert made[0].backend.config.name == "unitysvc"
    assert "[marketplace.home] (new)" in made[0].opening
    assert "## Fields of [marketplace.*]" in made[0].system


async def test_aimm_configure_routes_a_request_to_the_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.configure_util import ONE_ITEM

    config = tmp_path / "config.toml"
    config.write_text(ONE_ITEM, encoding="utf-8")
    made = use_fake_model(
        monkeypatch,
        [
            [("ask_user", {"message": "What would you like to change?"})],
            [("list_sections", {}), ("section_guide", {"section_type": "marketplace"})],
            [
                (
                    "section_update",
                    {
                        "section_type": "marketplace",
                        "name": "facebook",
                        "values": {"radius": [20]},
                    },
                )
            ],
            [("save", {"message": "Limiting the Houston search to 20 miles."})],
            [("finish", {"message": "Done."})],
        ],
    )
    ui = ScriptedSetupUI(["limit my Houston search to 20 miles", "yes"])
    assert await flow.configure_front_door(ui, [config], home=tmp_path) == 0
    assert read(config)["marketplace"]["facebook"]["radius"] == [20]
    assert read(config)["item"]["example"] == {
        "search_phrases": "road bike",
        "min_price": 50,
        "max_price": 300,
    }
    model = made[0]
    assert {"list_sections", "setup_ai", "section_guide", "section_update"} <= set(model.tools)
    assert "# The aimm-configure command" in model.system
    listed = model.results("list_sections")[0]["section_types"]
    assert {
        "type": "marketplace",
        "configurable_here": True,
        "sections": [{"name": "facebook", "request": None}],
    } in listed


async def test_ai_setup_only_when_the_default_ai_cannot_be_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[ai.openai]\napi_key = "${AIMM_TEST_UNSET_KEY}"\n', encoding="utf-8")
    monkeypatch.delenv("AIMM_TEST_UNSET_KEY", raising=False)
    setups: List[Any] = []

    async def fake_setup(ui: Any, files: Any, **kw: Any) -> int:
        setups.append(files)
        return 1

    monkeypatch.setattr(flow, "configure_ai", fake_setup)
    ui = ScriptedSetupUI([])
    assert await flow.configure_section(ui, [config], "marketplace", home=tmp_path) == 1
    assert len(setups) == 1
    assert "AIMM_TEST_UNSET_KEY" in ui.said("warning")[0]
    assert "Let's set up an AI service first." in ui.said("warning")[0]


async def test_configure_marketplace_reports_invalid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.configure_util import BASE

    config = tmp_path / "config.toml"
    config.write_text(BASE + '\n[marketplace.facebook]\ncondition = ["mint"]\n', encoding="utf-8")
    use_fake_model(monkeypatch, [])
    ui = ScriptedSetupUI([])
    assert await flow.configure_section(ui, [config], "marketplace", home=tmp_path) == 1
    assert "Cannot read the configuration" in ui.said("error")[0]


async def test_ctrl_c_inside_the_conversation_exits_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.configure_util import BASE

    config = tmp_path / "config.toml"
    config.write_text(BASE, encoding="utf-8")
    use_fake_model(monkeypatch, [[("ask_user", {"message": "Which city?"})]])
    ui = ScriptedSetupUI(["<close>"])
    assert await flow.configure_section(ui, [config], "marketplace", home=tmp_path) == 0


async def test_aimm_configure_without_an_ai_runs_ai_setup_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[user.me]\npushbullet_token = "abc"\n', encoding="utf-8")
    setups: List[Any] = []

    async def fake_setup(ui: Any, files: Any, **kw: Any) -> int:
        setups.append(files)
        return 0  # setup finished but still no usable AI section

    monkeypatch.setattr(flow, "configure_ai", fake_setup)
    ui = ScriptedSetupUI([])
    assert await flow.configure_front_door(ui, [config], home=tmp_path) == 1
    assert setups == [[config]]
    assert "No AI service is configured yet." in ui.said("error")
