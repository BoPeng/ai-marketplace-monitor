"""The item toolkit: field guides, the item's marketplace, checking, and a session with both."""

import sys
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, List

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.configure.agent import run_agent
from ai_marketplace_monitor.configure.flow import _opening, system_prompt
from ai_marketplace_monitor.configure.item import ITEM_GUIDES, ItemToolkit
from ai_marketplace_monitor.configure.marketplace import MarketplaceToolkit
from ai_marketplace_monitor.configure.toolkits import FieldGroup
from ai_marketplace_monitor.configure.tools import Outcome, ToolExecutor
from ai_marketplace_monitor.facebook import FacebookItemConfig
from tests.configure_util import BASE, ONE_ITEM, FakeModel, make_ws, ui_of, url

T = ItemToolkit()
KITS: Dict[str, Any] = {"marketplace": MarketplaceToolkit(), "item": T}


async def ws_for(tmp_path: Path, text: str, answers: Any = None) -> Any:
    return await make_ws(tmp_path, text, answers, toolkits=KITS)


# --- field guides -------------------------------------------------------------------------
def test_every_field_has_one_guide() -> None:
    expected = {f.name for f in fields(FacebookItemConfig)} - {
        "name",
        "request",
        "monitor_config",
        "searched_count",
    }
    names = [g.name for g in ITEM_GUIDES]
    assert sorted(names) == sorted(expected) and len(names) == len(set(names))


def test_shared_fields_default_to_the_marketplace() -> None:
    assert T.group("search_phrases") is FieldGroup.OWN
    assert T.group("radius") is FieldGroup.LOCATION
    assert T.guide("radius").default == "the marketplace's value"
    assert "only if this item should differ" in T.guide("radius").determine
    assert "user's words" in T.guide("extra_prompt").determine
    assert "explicitly" in T.guide("prompt").determine


async def test_completion_rules_name_what_missing_reports(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    completion = ws.playbooks["item"].body.split("## Completion", 1)[1].split("## ", 1)[0]
    for message in T.missing(ws, T.view(ws, "gopro")):
        assert message.split(":")[0] in completion


# --- the item's marketplace ---------------------------------------------------------------
async def test_show_extra_reports_what_the_item_inherits(tmp_path: Path) -> None:
    ws = await ws_for(
        tmp_path,
        ONE_ITEM.replace('search_city = "houston"', 'search_city = "houston"\nradius = 40'),
    )
    extra = T.show_extra(ws, T.view(ws, "example"))
    assert extra == {
        "marketplace": "facebook",
        "marketplace_exists": True,
        "inherited_from_marketplace": {"search_city": "houston", "radius": 40},
    }
    assert T.companions(ws, "example") == [("marketplace", "facebook")]


async def test_without_a_marketplace_the_item_asks_for_one(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft = T.view(ws, "gopro")
    assert T.show_extra(ws, draft)["marketplace_exists"] is False
    draft.values = {"search_phrases": ["gopro"]}
    assert T.validate(ws, draft) == []
    [message] = T.missing(ws, draft)
    assert message.startswith("marketplace: create [marketplace.facebook] with a location")
    # a marketplace drafted in this session counts, and its location is inherited
    ws.draft("marketplace", "facebook").values = {"search_city": "houston", "radius": 20}
    assert T.missing(ws, draft) == []
    assert T.show_extra(ws, draft)["inherited_from_marketplace"] == {
        "search_city": "houston",
        "radius": 20,
    }


async def test_location_comes_from_the_item_or_its_marketplace(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE + "\n[marketplace.facebook]\nmax_price = 500\n")
    draft = T.view(ws, "gopro")
    draft.values = {"search_phrases": ["gopro"]}
    assert T.missing(ws, draft) == [
        "location: set search_city (with radius) or search_region on the item or its marketplace"
    ]
    draft.values["search_city"] = "austin"
    assert T.missing(ws, draft) == []


# --- checking -----------------------------------------------------------------------------
async def test_validate(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, ONE_ITEM)
    draft = T.view(ws, "gopro")
    draft.values = {"rating": [7]}  # checked before the search phrases are known
    assert "rating" in T.validate(ws, draft)[0]
    draft.values = {"search_phrases": ["gopro"], "notify": ["bob"]}
    assert T.validate(ws, draft) == [
        "`notify` names ['bob'], which are not in can_reference.users."
    ]
    draft.values = {"search_phrases": ["gopro"], "marketplace": "other"}
    assert "can_reference.marketplaces" in T.validate(ws, draft)[0]
    draft.values = {"search_phrases": ["gopro"], "max_price": "200", "extra_prompt": "no repairs"}
    assert T.validate(ws, draft) == []


async def test_start_menu(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, ONE_ITEM, ["example"])
    assert await T.choose_target(ws.ui, ws, None) == "example"
    assert "**[item.example]**" in "\n".join(ui_of(ws).said())
    ws = await ws_for(tmp_path, ONE_ITEM, ["__new__", "example", "gopro"])
    assert await T.choose_target(ws.ui, ws, None) == "gopro"
    ws = await ws_for(tmp_path, BASE, [""])
    assert await T.choose_target(ws.ui, ws, None) == "item_1"


# --- an item session that also creates the marketplace -----------------------------------------
async def test_item_session_creates_its_marketplace(tmp_path: Path) -> None:
    answer = f"action camera under $200 within 20 miles of {url('houston')}"
    ws = await ws_for(tmp_path, BASE, [answer, "yes"])
    only = [("item", "action_camera"), *T.companions(ws, "action_camera")]
    executor = ToolExecutor(ws, only=set(only))
    executor.guides_read.update(["item", "marketplace"])
    model = FakeModel(
        [
            [
                ("section_show", {"section_type": "item", "name": "action_camera"}),
                ("ask_user", {"message": "What are you looking for?"}),
            ],
            [
                (
                    "section_update",
                    {
                        "section_type": "item",
                        "name": "action_camera",
                        "values": '{"search_phrases": ["action camera", "gopro"], '
                        '"max_price": "200", "extra_prompt": "no repairs"}',
                    },
                ),
                (
                    "section_update",
                    {
                        "section_type": "marketplace",
                        "name": "facebook",
                        "values": {"search_city": "houston", "radius": 20},
                    },
                ),
                ("save", {"message": "Saving the item and its marketplace."}),
            ],
            [("finish", {"message": "Done."})],
        ]
    ).bind(executor.tools_for_model(), lambda: executor.done)
    prompt = system_prompt(ws, ["item", "marketplace"])
    assert "# Task: [item.*]" in prompt and "# Task: [marketplace.*]" in prompt
    opening = _opening(ws, only)
    assert "[item.action_camera] (new)" in opening and "[marketplace.facebook]" in opening
    outcome = await run_agent(executor, model, prompt, opening)
    assert outcome is Outcome.SAVED
    shown = model.results("section_show")[0]
    assert shown["marketplace_exists"] is False
    written = tomllib.loads((tmp_path / "config.toml").read_text())
    assert written["marketplace"]["facebook"] == {"search_city": "houston", "radius": 20}
    assert written["item"]["action_camera"] == {
        "search_phrases": ["action camera", "gopro"],
        "max_price": "200",
        "extra_prompt": "no repairs",
    }
    assert ui_of(ws).questions.count("Write these changes?") == 1


async def test_item_session_cannot_touch_other_sections(tmp_path: Path) -> None:
    ws = await ws_for(
        tmp_path, ONE_ITEM.replace("[item.example]", "[item.example]\nenabled = true")
    )
    executor = ToolExecutor(ws, only={("item", "gopro"), ("marketplace", "facebook")})
    executor.guides_read.update(["item", "marketplace"])
    out = await executor.call(
        "section_update",
        {"section_type": "item", "name": "example", "values": {"max_price": "1"}},
    )
    assert out["ok"] is False
    assert out["errors"] == [
        "Only [item.gopro], [marketplace.facebook] can be changed in this session."
    ]


async def test_an_incomplete_item_does_not_block_its_marketplace(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    ws.user_said.append(url("houston"))
    ws.draft("item", "gopro").values = {"max_price": "200"}  # no search phrases yet
    market = ws.draft("marketplace", "facebook")
    market.values = {"search_city": "houston", "radius": 20}
    assert MarketplaceToolkit().validate(ws, market) == []
    assert "item" not in ws.config_with_drafts()


async def test_an_item_city_must_come_from_a_pasted_url(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, ONE_ITEM)
    draft = T.view(ws, "gopro")
    draft.values = {"search_phrases": ["gopro"], "search_city": "houston"}  # the marketplace's
    assert T.validate(ws, draft) == []
    draft.values["search_city"] = "dallas"
    assert "Never guess" in T.validate(ws, draft)[0]


async def test_an_item_may_name_a_section_drafted_in_the_session(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, ONE_ITEM)
    draft = T.view(ws, "gopro")
    draft.values = {"search_phrases": ["gopro"], "notify": ["alice"]}
    assert "can_reference.users" in T.validate(ws, draft)[0]
    ws.toolkits["user"] = _UserStub()
    ws.draft("user", "alice").values = {"email": "alice@example.com"}
    assert "alice" in T.context(ws)["users"]


class _UserStub(MarketplaceToolkit):
    """A stand-in user toolkit: any drafted user is complete."""

    section_type = "user"

    def missing(self: "_UserStub", ws: Any, draft: Any) -> List[str]:
        return []

    def view(self: "_UserStub", ws: Any, name: str) -> Any:
        from ai_marketplace_monitor.configure.toolkits import SectionDraft

        return SectionDraft("user", name, True, None, {})
