"""The marketplace toolkit: field guides, reading, checking and applying a section."""

from dataclasses import fields
from pathlib import Path

import pytest

from ai_marketplace_monitor.configure.marketplace import MARKETPLACE_GUIDES, MarketplaceToolkit
from ai_marketplace_monitor.configure.playbooks import load_playbook
from ai_marketplace_monitor.configure.toolkits import FieldGroup
from ai_marketplace_monitor.facebook import (
    Condition,
    DeliveryMethod,
    FacebookMarketplaceConfig,
    SortBy,
)
from ai_marketplace_monitor.marketplace import FALLBACK, LOCATION
from tests.configure_util import BASE, ONE_ITEM, make_ws, ui_of, url

T = MarketplaceToolkit()
ITEMS = (
    BASE
    + """
[marketplace.facebook]
search_city = "houston"
radius = 40
condition = ["used_good"]

[item.bike]
search_phrases = "bike"

[item.desk]
search_phrases = "desk"
search_city = "dallas"
radius = 20
"""
)


# --- field guides -------------------------------------------------------------------------
def test_every_field_has_one_guide() -> None:
    expected = {f.name for f in fields(FacebookMarketplaceConfig)} - {
        "name",
        "request",
        "monitor_config",
    }
    names = [g.name for g in MARKETPLACE_GUIDES]
    assert sorted(names) == sorted(expected) and len(names) == len(set(names))


def test_groups_come_from_metadata() -> None:
    for f in fields(FacebookMarketplaceConfig):
        if f.name in ("name", "request", "monitor_config"):
            continue
        expected = (
            FieldGroup.LOCATION
            if f.metadata.get(LOCATION)
            else FieldGroup.SHARED if f.metadata.get(FALLBACK) else FieldGroup.OWN
        )
        assert T.group(f.name) is expected


@pytest.mark.parametrize(
    "field, enum",
    [("condition", Condition), ("delivery_method", DeliveryMethod), ("sort_by", SortBy)],
)
def test_enum_formats_list_every_value(field: str, enum: type) -> None:
    assert all(repr(e.value) in T.guide(field).format for e in enum)  # type: ignore[attr-defined]


async def test_completion_rules_name_what_missing_reports(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, BASE)
    completion = ws.playbooks["marketplace"].body.split("## Completion", 1)[1].split("## ", 1)[0]
    for message in T.missing(ws, T.view(ws, "facebook")):
        assert message.split(":")[0] in completion
    assert "search_city" in completion and "search_region" in completion


def test_playbook_explains_url_codes() -> None:
    text = load_playbook("marketplace").text()
    assert "never guess it" in text and "paste the URL" in text and "`111979382146893`" in text


# --- reading and checking ------------------------------------------------------------------
async def test_view(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, ITEMS)
    new = T.view(ws, "other")
    assert new.is_new and new.values == {} and new.request is None
    draft = T.view(ws, "facebook")
    assert not draft.is_new
    assert draft.values == {"search_city": "houston", "radius": 40, "condition": ["used_good"]}
    assert T.missing(ws, draft) == []
    assert T.missing(ws, new) == ["location: set search_city (with radius) or search_region"]


async def test_validate(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, BASE)
    ws.user_said += [url("houston"), url("austin")]
    draft = T.view(ws, "facebook")
    draft.values = {"search_city": ["houston"], "condition": ["mint"]}
    assert "condition" in T.validate(ws, draft)[0]
    draft.values = {"search_city": ["houston"], "notify": ["bob"]}
    assert T.validate(ws, draft) == [
        "`notify` names ['bob'], which are not in can_reference.users."
    ]
    draft.values = {"search_city": ["houston", "austin"], "radius": [10, 20, 30]}
    assert T.validate(ws, draft)  # cross-field error found by loading the result


@pytest.mark.parametrize(
    "city, ok",
    [
        ("houston", True),
        (["sanfrancisco", "111979382146893"], True),
        ("https://www.facebook.com/marketplace/bogota/search?query=iphone", False),
        ("san francisco", False),
    ],
)
async def test_search_city_must_be_a_location_code(tmp_path: Path, city: object, ok: bool) -> None:
    ws = await make_ws(tmp_path, BASE)
    ws.user_said += [url("houston"), url("sanfrancisco"), url("111979382146893")]
    draft = T.view(ws, "facebook")
    draft.values = {"search_city": city}
    errors = T.validate(ws, draft)
    assert (errors == []) is ok
    if not ok:
        assert "search_city" in errors[0] and "incorrect format" in errors[0]


async def test_city_name_only_changes_with_a_new_city(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, ONE_ITEM)
    draft = T.view(ws, "facebook")
    draft.values["city_name"] = ["Houston"]
    assert "`city_name` may only change" in T.validate(ws, draft)[0]
    draft.values = {"search_city": ["austin"], "city_name": ["Austin"]}
    ws.user_said.append(url("austin"))
    assert T.validate(ws, draft) == []


# --- changing ------------------------------------------------------------------------------
async def test_change_rejects_unknown_fields_secrets_and_references(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, ONE_ITEM)
    draft = T.view(ws, "facebook")
    new, problems = T.change(
        draft,
        {
            "colour": "red",
            "password": "hunter2",
            "username": "${FACEBOOK_USERNAME}",
            "city_name": ["${HOME}"],
            "max_price": "1000",
        },
        [],
        "Max price $1000.",
    )
    assert problems == [
        "`colour` is not a field of [marketplace.*].",
        "`password` is secret: only a ${VAR} reference may be set.",
        "`city_name` may not contain a ${VAR} reference.",
    ]
    assert new.values == {
        "search_city": "houston",
        "username": "${FACEBOOK_USERNAME}",
        "max_price": "1000",
    }
    assert new.request == "Max price $1000."
    assert draft.values == {"search_city": "houston"}  # the input is not changed


async def test_same_value_in_another_form_is_not_a_change(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, ONE_ITEM)
    draft = T.view(ws, "facebook")
    new, problems = T.change(draft, {"search_city": ["houston"]}, [], None)
    assert problems == [] and new.values == {"search_city": "houston"}
    assert not new.has_changes()


async def test_apply_replaces_only_the_marketplace_section(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, ITEMS)
    draft = T.view(ws, "facebook")
    draft.values.update({"search_city": "austin", "max_price": "1000"})
    draft.request = "Austin; max $1000."
    cfg = T.apply(ws.user_cfg, draft)
    assert cfg["marketplace"]["facebook"] == {
        "request": "Austin; max $1000.",
        "search_city": "austin",
        "radius": 40,
        "condition": ["used_good"],
        "max_price": "1000",
    }
    assert {k: v for k, v in cfg.items() if k != "marketplace"} == {
        k: v for k, v in ws.user_cfg.items() if k != "marketplace"
    }
    assert ws.user_cfg["marketplace"]["facebook"]["search_city"] == "houston"


async def test_secrets_are_masked(tmp_path: Path) -> None:
    ws = await make_ws(
        tmp_path,
        BASE + '\n[marketplace.facebook]\nsearch_city = "houston"\nusername = "me@example.com"\n',
    )
    draft = T.view(ws, "facebook")
    assert T.masked(draft.values)["username"] == "<set; hidden>"
    assert "me@example.com" not in T.describe(draft)


# --- the start menu (aimm-configure marketplace) ---------------------------------------------
async def test_start_menu_lists_marketplaces_without_item_details(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, ONE_ITEM, ["facebook"])
    assert await T.choose_target(ws.ui, ws, None) == "facebook"
    shown = "\n".join(ui_of(ws).said())
    assert "**[marketplace.facebook]** (1 item)" in shown and 'search_city = "houston"' in shown
    assert "[item." not in shown and "max_price" not in shown


async def test_start_menu_quit_new_and_names(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, ONE_ITEM, ["__quit__"])
    assert await T.choose_target(ws.ui, ws, None) is None
    ws = await make_ws(tmp_path, ONE_ITEM, ["__new__", "bad name", ""])
    assert await T.choose_target(ws.ui, ws, None) == "facebook_2"
    ws = await make_ws(tmp_path, BASE)
    assert await T.choose_target(ws.ui, ws, None) == "facebook"
    assert await T.choose_target(ws.ui, ws, "home") == "home"
    assert "[marketplace.home] is new." in ui_of(ws).said()


async def test_search_city_must_come_from_a_pasted_url(tmp_path: Path) -> None:
    ws = await make_ws(tmp_path, ONE_ITEM)
    draft = T.view(ws, "facebook")
    draft.values = {"search_city": ["houston"]}  # already in the config
    assert T.validate(ws, draft) == []
    draft.values = {"search_city": ["austin"], "city_name": ["Austin"]}
    [error] = T.validate(ws, draft)
    assert "['austin'] is not from a Facebook Marketplace URL" in error and "Never guess" in error
    ws.user_said.append("I'm in Austin, here: https://m.facebook.com/marketplace/austin/?ref=x")
    assert T.validate(ws, draft) == []
    # paths that are not locations do not count
    ws.user_said = ["https://www.facebook.com/marketplace/search/?query=bike"]
    draft.values = {"search_city": ["search"]}
    assert "not from a Facebook Marketplace URL" in T.validate(ws, draft)[0]
