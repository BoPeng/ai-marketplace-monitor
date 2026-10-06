"""The configure tools (executor), called directly: no LLM involved."""

import json
import sys
from pathlib import Path
from typing import Any, Dict

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.configure.tools import Outcome, ToolExecutor
from tests.configure_util import BASE, ONE_ITEM, make_ws, ui_of, url


def ready(ws: Any, **kw: Any) -> ToolExecutor:
    """An executor that has read the marketplace guide."""
    ex = ToolExecutor(ws, **kw)
    ex.guides_read.add("marketplace")
    return ex


async def call(ex: ToolExecutor, tool: str, **args: Any) -> Dict[str, Any]:
    out = await ex.call(tool, args)
    out.pop("session_state", None)
    return out


async def test_show_returns_only_the_section_and_names(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM))
    out = await call(ex, "section_show", section_type="marketplace", name="facebook")
    assert out["ok"] and out["exists"]
    assert out["saved_values"] == out["values"] == {"search_city": "houston"}
    assert out["unsaved_changes"] == {} and out["still_required"] == []
    assert out["can_reference"]["users"] == ["me"]
    assert "example" not in str(out) and "abc" not in str(out)  # no items, no secrets


async def test_update_validates_and_keeps_the_draft_on_errors(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM))
    bad = await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="facebook",
        values={"condition": ["mint"]},
    )
    assert not bad["ok"] and "condition" in bad["errors"][0]
    good = await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="facebook",
        values={"max_price": "1000"},
        request="Max $1000.",
    )
    assert good["ok"] and good["unsaved_changes"] == {"max_price": "1000"}
    assert ex.ws.drafts[("marketplace", "facebook")].request == "Max $1000."
    assert (tmp_path / "config.toml").read_text().count("max_price") == 1  # only the item's


async def test_non_secret_reference_is_rejected_and_never_expanded(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("AIMM_TEST_SECRET", "s3cret-value")
    ex = ready(await make_ws(tmp_path, ONE_ITEM))
    out = await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="facebook",
        values={"prompt": "${AIMM_TEST_SECRET}"},
    )
    assert not out["ok"] and "may not contain a ${VAR}" in out["errors"][0]
    assert "s3cret-value" not in str(out) and "s3cret-value" not in str(ex.ws.drafts)


async def test_single_section_restriction(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM), only={("marketplace", "facebook")})
    out = await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="other",
        values={"search_city": "dallas"},
    )
    assert out == {
        "ok": False,
        "errors": ["Only [marketplace.facebook] can be changed in this session."],
    }
    names = [fn.__name__ for fn in ex.tools_for_model()]
    assert "list_sections" not in names and "section_update" in names


async def test_list_sections_shows_names_requests_and_summaries(tmp_path: Path) -> None:
    ws = await make_ws(
        tmp_path,
        ONE_ITEM.replace("[marketplace.facebook]", '[marketplace.facebook]\nrequest = "Houston"'),
    )
    out = await call(ready(ws), "list_sections")
    by_type = {t["type"]: t for t in out["section_types"]}
    assert by_type["marketplace"] == {
        "type": "marketplace",
        "configurable_here": True,
        "sections": [{"name": "facebook", "request": "Houston", "summary": "searches houston"}],
    }
    assert by_type["item"]["configurable_here"] is False
    assert by_type["ai"]["sections"] == [{"name": "unitysvc", "request": None}]
    assert "svcpass_testkey" not in str(out) and "abc" not in str(out)  # no secrets


async def test_save_writes_drafts_after_one_confirmation(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM, ["yes"]))
    ex.ws.user_said.append(url("austin"))
    await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="facebook",
        values={"max_price": "1000"},
    )
    await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="home",
        values={"search_city": "austin"},
    )
    out = await call(ex, "save", message="Saving.")
    assert out == {
        "ok": True,
        "saved": True,
        "sections": ["[marketplace.facebook]", "[marketplace.home]"],
    }
    written = tomllib.loads((tmp_path / "config.toml").read_text())
    assert written["marketplace"]["facebook"]["max_price"] == "1000"
    assert written["marketplace"]["home"] == {"search_city": "austin"}
    assert written["item"]["example"]["max_price"] == 300  # items untouched
    assert ui_of(ex.ws).questions == ["Write these changes?"]
    assert ex.ws.drafts == {} and ex.outcome is Outcome.SAVED


async def test_save_refuses_incomplete_and_reports_declined(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, BASE, ["no"]))
    await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="facebook",
        values={"condition": ["new"]},
    )
    out = await call(ex, "save", message="")
    assert not out["ok"] and "still required: location" in out["errors"][0]
    ex.ws.user_said.append(url("houston"))
    await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="facebook",
        values={"search_city": "houston"},
    )
    out = await call(ex, "save", message="")
    assert out["declined"] and not out["saved"]
    assert "marketplace" not in (tmp_path / "config.toml").read_text()


async def test_save_with_nothing_pending(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM))
    await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="facebook",
        request="Only a new summary.",
    )
    assert await call(ex, "save", message="") == {
        "ok": True,
        "saved": False,
        "note": "Nothing to save: no unsaved changes.",
    }


async def test_finish_refuses_unsaved_changes_unless_discarded(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM))
    await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="facebook",
        values={"max_price": "1000"},
    )
    out = await call(ex, "finish", message="Bye.")
    assert not out["ok"] and "max_price='1000'" in out["errors"][0] and not ex.done
    assert (await call(ex, "finish", message="Bye.", discard_unsaved=True))["ok"]
    assert ex.done and ex.outcome is Outcome.CANCELLED


async def test_ask_user_commands(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM, ["/show", "Houston is fine", "/quit"]))
    await call(
        ex,
        "section_update",
        section_type="marketplace",
        name="facebook",
        values={"max_price": "1000"},
    )
    assert (await call(ex, "ask_user", message="Anything else?"))["reply"] == "Houston is fine"
    assert any('max_price = "1000"' in m for m in ui_of(ex.ws).said())  # /show
    out = await call(ex, "ask_user", message="And?")
    assert out["reply"] is None and ex.done and ex.outcome is Outcome.CANCELLED


async def test_force_ask_and_ended_session(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM))
    ex.force_ask = True
    out = await call(ex, "section_show", section_type="marketplace", name="facebook")
    assert out["errors"] == ["Too many steps without the user: call ask_user now."]
    ex.force_ask = False
    ex.end()
    assert (await call(ex, "section_show", section_type="marketplace", name="facebook"))[
        "errors"
    ] == ["The session has ended."]


async def test_tools_for_model_have_names_and_docs(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM))
    tools = {fn.__name__: fn for fn in ex.tools_for_model()}
    assert set(tools) == {
        "ask_user",
        "save",
        "finish",
        "list_sections",
        "section_guide",
        "section_show",
        "section_update",
        "section_check",
    }
    assert all(
        fn.__doc__ and "Args:" in fn.__doc__ for n, fn in tools.items() if n != "list_sections"
    )
    out = await tools["section_update"](
        section_type="marketplace", name="facebook", values='{"max_price": "5"}'
    )
    assert out["ok"] and ex.calls[-1] == (
        "section_update",
        {
            "section_type": "marketplace",
            "name": "facebook",
            "values": '{"max_price": "5"}',
            "unset": None,
            "request": None,
        },
    )


async def test_update_values_as_a_json_string(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM))
    tools = {fn.__name__: fn for fn in ex.tools_for_model()}
    out = await tools["section_update"](
        section_type="marketplace", name="facebook", values='{"radius": [20]}'
    )
    assert out["ok"] and out["unsaved_changes"] == {"radius": [20]}
    bad = await tools["section_update"](
        section_type="marketplace", name="facebook", values="{radius: 20"
    )
    assert not bad["ok"] and "not valid JSON" in bad["errors"][0]
    double = await tools["section_update"](
        section_type="marketplace", name="facebook", values=json.dumps('{"radius": [25]}')
    )
    assert double["ok"] and double["unsaved_changes"] == {"radius": [25]}
    wrong = await tools["section_update"](
        section_type="marketplace", name="facebook", values="[20]"
    )
    assert not wrong["ok"] and "must be one JSON object" in wrong["errors"][0]


async def test_guide_is_required_before_updating(tmp_path: Path) -> None:
    ex = ToolExecutor(await make_ws(tmp_path, ONE_ITEM))
    out = await call(
        ex, "section_update", section_type="marketplace", name="facebook", values="{}"
    )
    assert out["errors"] == ["Read the rules first: call section_guide('marketplace')."]
    guide = await call(ex, "section_guide", section_type="marketplace")
    assert "## Goal" in guide["playbook"] and "| `search_city` |" in guide["fields"]
    out = await call(
        ex, "section_update", section_type="marketplace", name="facebook", values='{"radius": [5]}'
    )
    assert out["ok"]
    unknown = await call(ex, "section_guide", section_type="item")
    assert unknown["errors"] == ["[item.*] sections cannot be configured here."]


async def test_session_state_tracks_drafts(tmp_path: Path) -> None:
    ex = ready(await make_ws(tmp_path, ONE_ITEM))
    await ex.call(
        "section_update",
        {"section_type": "marketplace", "name": "home", "values": '{"condition": ["new"]}'},
    )
    out = await ex.call("list_sections", {})
    assert out["session_state"] == {
        "drafts": [
            {
                "section": "marketplace.home",
                "unsaved_changes": {"condition": ["new"]},
                "complete": False,
            }
        ],
        "last_section": "marketplace.home",
    }
