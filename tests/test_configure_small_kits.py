"""The [monitor], [region.*] and [translation.*] toolkits."""

import re
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import ai_marketplace_monitor
from ai_marketplace_monitor.configure import flow
from ai_marketplace_monitor.configure.flow import _opening
from ai_marketplace_monitor.configure.small_kits import (
    LABELS,
    MonitorToolkit,
    RegionToolkit,
    TranslationToolkit,
)
from ai_marketplace_monitor.configure.tools import ToolExecutor
from ai_marketplace_monitor.configure.ui import ScriptedSetupUI
from ai_marketplace_monitor.utils import MonitorConfig
from tests.configure_util import BASE, ONE_ITEM, make_ws, ui_of, url

M, R, T = MonitorToolkit(), RegionToolkit(), TranslationToolkit()
KITS: Dict[str, Any] = {"monitor": M, "region": R, "translation": T}


async def ws_for(tmp_path: Path, text: str, answers: Any = None) -> Any:
    return await make_ws(tmp_path, text, answers, toolkits=KITS)


async def session(tmp_path: Path, text: str, answers: Any, only: Any) -> ToolExecutor:
    ex = ToolExecutor(await ws_for(tmp_path, text, answers), only=only)
    ex.guides_read.update(KITS)
    return ex


# --- [monitor] -------------------------------------------------------------------------------
def test_monitor_guides_cover_its_fields() -> None:
    names = {f.name for f in fields(MonitorConfig)} - {"name", "request", "enabled"}
    assert sorted(M.field_names()) == sorted(names)


async def test_monitor_checks(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE + '\n[monitor]\nproxy_password = "hunter2"\n')
    draft = M.view(ws, "monitor")
    assert not draft.is_new and M.masked(draft.values) == {"proxy_password": "<set; hidden>"}
    assert M.missing(ws, draft) == ["proxy_server: a user name or password needs the proxy itself"]
    _, problems = M.change(draft, {"proxy_username": "me"}, [], None)
    assert problems == ["`proxy_username` is secret: only a ${VAR} reference may be set."]
    new, problems = M.change(draft, {"proxy_server": "${PROXY_SERVER}"}, [], None)
    assert problems == [] and new.values["proxy_server"] == "${PROXY_SERVER}"
    _, problems = M.change(draft, {"proxy_server": "http://${HOST}:8080"}, [], None)
    assert problems == ["`proxy_server` may not contain a ${VAR} reference."]
    draft.values = {"proxy_server": "http://p:1", "proxy_username": "${PROXY_USERNAME}"}
    assert M.missing(ws, draft) == [
        "proxy_username and proxy_password: the proxy needs both, or neither"
    ]


async def test_monitor_is_written_as_one_section(tmp_path: Path) -> None:
    ex = await session(tmp_path, ONE_ITEM, ["yes"], {("monitor", "monitor")})
    out = await ex.call(
        "section_update",
        {
            "section_type": "monitor",
            "name": "monitor",
            "values": {"proxy_server": "http://proxy.example.com:8080"},
        },
    )
    assert out["ok"], out
    saved = await ex.call("save", {"message": ""})
    assert saved["sections"] == ["[monitor]"]
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert tomllib.loads(text)["monitor"] == {"proxy_server": "http://proxy.example.com:8080"}
    listed = await ToolExecutor(ex.ws).call("list_sections", {})
    assert {
        "type": "monitor",
        "configurable_here": True,
        "sections": [{"name": "monitor", "request": None}],
    } in listed["section_types"]
    opening = _opening(ex.ws, [("monitor", "monitor")])
    assert "The active section is [monitor] (existing)" in opening


async def test_other_sections_cannot_change_in_a_monitor_session(tmp_path: Path) -> None:
    ex = await session(tmp_path, ONE_ITEM, [], {("monitor", "monitor")})
    out = await ex.call("section_show", {"section_type": "region", "name": "x"})
    assert out["errors"] == ["Only [monitor] can be changed in this session."]


# --- [region.*] -------------------------------------------------------------------------------
async def test_a_new_region_needs_cities_from_pasted_urls(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft = R.view(ws, "gulf")
    assert R.missing(ws, draft) == [
        "search_city: the cities of the region, from pasted Marketplace URLs"
    ]
    draft.values = {"search_city": ["galveston", "portland"], "radius": 40}
    assert "Never guess" in R.validate(ws, draft)[0]
    ws.user_said.append(url("galveston"))  # portland is in a built-in region
    assert R.validate(ws, draft) == [] and R.missing(ws, draft) == []
    draft.values["city_name"] = ["Galveston"]
    assert "same length" in R.validate(ws, draft)[0]


async def test_a_built_in_region_can_be_changed_in_part(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft = R.view(ws, "usa")
    assert draft.is_new and R.missing(ws, draft) == []  # the built-in cities apply
    draft.values = {"radius": 300}
    assert R.validate(ws, draft) == []
    extra = R.show_extra(ws, draft)
    assert extra["built_in"]["search_city"] and "usa" in extra["built_in_regions"]
    assert "usa" in R.context(ws)["regions"]


# --- [translation.*] --------------------------------------------------------------------------
def test_labels_are_the_ones_aimm_looks_for() -> None:
    source = Path(ai_marketplace_monitor.__file__).parent / "facebook.py"
    used = set(
        re.findall(
            r"""translator\(\s*(?:"([^"]+)"|'([^']+)')""", source.read_text(encoding="utf-8")
        )
    )
    used_labels = {a or b for a, b in used} - {"**unspecified**"}
    assert used_labels <= set(LABELS)


async def test_translation_checks(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft = T.view(ws, "de")
    assert T.missing(ws, draft) == ["locale: the language of the user's Facebook"]
    _, problems = T.change(draft, {"Price": "Preis"}, [], None)
    assert problems == ["`Price` is not a field of [translation.*]."]
    draft.values = {"locale": "German", "Condition": 3}
    assert T.validate(ws, draft) == ["`Condition` must be text."]
    draft.values = {"locale": "German", "Condition": "Zustand", "Seller's description": "x"}
    assert T.validate(ws, draft) == [] and T.missing(ws, draft) == []
    assert "must match the page exactly" in T.describe(draft)
    extra = T.show_extra(ws, draft)
    assert set(extra["built_in_examples"]) >= {"es", "zh"}
    assert extra["used_by_marketplaces"] == []


async def test_translation_is_saved_with_its_labels(tmp_path: Path) -> None:
    ex = await session(tmp_path, BASE, ["yes"], {("translation", "*")})
    values = (
        '{"locale": "German", "Condition": "Zustand", "Seller\'s description": "Beschreibung"}'
    )
    out = await ex.call(
        "section_update", {"section_type": "translation", "name": "de", "values": values}
    )
    assert out["ok"], out
    assert (await ex.call("save", {"message": ""}))["saved"]
    written = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert written["translation"]["de"] == {
        "locale": "German",
        "Condition": "Zustand",
        "Seller's description": "Beschreibung",
    }


async def test_start_lists_mine_and_built_in(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    assert await T.choose_target(ws.ui, ws, None) == "*"
    shown = ui_of(ws).said()[0]
    assert "no [translation.*] section yet" in shown and "Built in: es, zh, sv" in shown
    opening = _opening(ws, [("translation", "*"), ("translation", "*")])
    assert "You may change any [translation.*]. Ask the user" in opening


# --- commands -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "section, target",
    [
        ("monitor", ("monitor", None)),
        ("region", ("region", None)),
        ("translation.de", ("translation", "de")),
    ],
)
async def test_commands(monkeypatch: pytest.MonkeyPatch, section: str, target: Any) -> None:
    runs = []

    async def fake_ai(ui: Any, files: Any, home: Any = None) -> str:
        return "backend"

    async def fake_session(ui: Any, files: Any, ai: Any, kits: Any, **kw: Any) -> int:
        runs.append((sorted(kits), kw["target"]))
        return 0

    monkeypatch.setattr(flow, "ai_for_configure", fake_ai)
    monkeypatch.setattr(flow, "run_session", fake_session)
    assert await flow.configure_section(ScriptedSetupUI([]), [], section) == 0
    assert runs == [([target[0]], target)]
    with pytest.raises(flow.ConfigureAddressError):
        flow.validate_section_address("monitor.x")
