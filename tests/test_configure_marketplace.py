import sys
from dataclasses import fields
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.configure import llm
from ai_marketplace_monitor.configure.marketplace import MARKETPLACE_GUIDES, MarketplaceBuilder
from ai_marketplace_monitor.configure.sections import FieldGroup, TurnError
from ai_marketplace_monitor.configure.ui import ScriptedSetupUI
from ai_marketplace_monitor.facebook import (
    Condition,
    DeliveryMethod,
    FacebookMarketplaceConfig,
    SortBy,
)
from ai_marketplace_monitor.marketplace import FALLBACK, LOCATION
from tests.configure_util import BASE, make_ctx, reply

B = MarketplaceBuilder()
ITEMS = (
    BASE
    + """
[marketplace.facebook]
search_city = "houston"
radius = 40
condition = ["used_good"]

[item.bike]
search_phrases = "bike"

[item.sofa]
search_phrases = "sofa"

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
    assert sorted(names) == sorted(expected)
    assert len(names) == len(set(names))


def test_groups_come_from_metadata() -> None:
    for f in fields(FacebookMarketplaceConfig):
        if f.name in ("name", "request", "monitor_config"):
            continue
        group = B.group(f.name)
        if f.metadata.get(LOCATION):
            assert group is FieldGroup.LOCATION
        elif f.metadata.get(FALLBACK):
            assert group is FieldGroup.SHARED
        else:
            assert group is FieldGroup.OWN
    assert B.group("search_region") is FieldGroup.LOCATION
    assert B.group("username") is FieldGroup.OWN


@pytest.mark.parametrize(
    "field, enum",
    [("condition", Condition), ("delivery_method", DeliveryMethod), ("sort_by", SortBy)],
)
def test_enum_formats_list_every_value(field: str, enum: type) -> None:
    text = B.guide(field).format
    assert all(repr(e.value) in text for e in enum)  # type: ignore[attr-defined]


def test_completion_rules_name_what_missing_reports(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE)
    completion = ctx.playbooks["marketplace"].body.split("## Completion", 1)[1].split("## ", 1)[0]
    for message in B.missing(ctx, B.view(ctx, "facebook")):
        assert message.split(":")[0] in completion
        for field_name in ("search_city", "search_region"):
            assert field_name in completion


# --- view / missing / validate ----------------------------------------------------------------
def test_view_of_new_marketplace(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE)
    draft = B.view(ctx, "facebook")
    assert draft.is_new and draft.values == {} and draft.request is None
    assert B.missing(ctx, draft) == ["location: set search_city (with radius) or search_region"]


def test_view_with_items_shows_shared_and_varying_values(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    draft = B.view(ctx, "facebook")
    assert not draft.is_new
    assert draft.values["condition"] == ["used_good"]
    assert "notify" not in draft.values and "ai" not in draft.values  # the defaults
    assert draft.varies["search_city"] == {"bike": "houston", "sofa": "houston", "desk": "dallas"}
    assert "search_city" not in draft.values
    assert B.missing(ctx, draft) == []  # every item has a location


def test_validate_reports_bad_values_and_unknown_names(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE)
    draft = B.view(ctx, "facebook")
    draft.values = {"search_city": ["houston"], "condition": ["mint"]}
    assert "condition" in B.validate(ctx, draft)[0]
    draft.values = {"search_city": ["houston"], "notify": ["bob"], "ai": ["unitysvc"]}
    assert B.validate(ctx, draft) == ["`notify` names ['bob'], which are not in context.users."]
    draft.values = {"search_city": ["houston", "austin"], "radius": [10, 20, 30]}
    assert B.validate(ctx, draft)  # cross-field error found by expanding the result


# --- apply ------------------------------------------------------------------------------------
def test_apply_without_items_keeps_values_on_marketplace(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE)
    draft = B.view(ctx, "facebook")
    draft.values = {"search_city": ["houston"], "radius": [40], "condition": ["used_good"]}
    draft.request = "Houston, 40 miles, good used items."
    market = B.apply(ctx, draft)["marketplace"]["facebook"]
    assert market == {
        "request": "Houston, 40 miles, good used items.",
        "search_city": ["houston"],
        "radius": [40],
        "condition": ["used_good"],
    }
    assert "marketplace" not in ctx.expanded  # input untouched


def test_apply_changes_only_items_using_the_shared_value(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    draft = B.view(ctx, "facebook")
    draft.values["condition"] = ["new"]
    items = B.apply(ctx, draft)["item"]
    assert all(items[n]["condition"] == ["new"] for n in ("bike", "sofa", "desk"))


def test_apply_location_keeps_items_with_their_own(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    draft = B.view(ctx, "facebook")
    draft.values.update({"search_city": ["austin"], "radius": [25]})
    items = B.apply(ctx, draft)["item"]
    assert (items["bike"]["search_city"], items["bike"]["radius"]) == (["austin"], [25])
    assert (items["sofa"]["search_city"], items["sofa"]["radius"]) == (["austin"], [25])
    assert (items["desk"]["search_city"], items["desk"]["radius"]) == ("dallas", 20)


def test_apply_to_all_items(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    draft = B.view(ctx, "facebook")
    draft.values.update({"search_city": ["austin"], "radius": [25]})
    draft.all_items = {"search_city"}
    items = B.apply(ctx, draft)["item"]
    assert items["desk"]["search_city"] == ["austin"] and items["desk"]["radius"] == [25]


def test_describe_lists_changed_items(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    draft = B.view(ctx, "facebook")
    draft.values["condition"] = ["new"]
    text = B.describe(ctx, draft)
    assert "[marketplace.facebook]" in text
    assert "Items updated:" in text and "bike (condition)" in text
    assert "`search_city` differs across items" in text


def test_secrets_are_masked(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        BASE + '\n[marketplace.facebook]\nsearch_city = "houston"\nusername = "me@example.com"\n',
    )
    draft = B.view(ctx, "facebook")
    assert B.masked(draft.values)["username"] == "<set; hidden>"
    assert "me@example.com" not in B.describe(ctx, draft)
    messages = llm.build_messages(B, ctx, draft, [], [])
    assert "me@example.com" not in str(messages)


# --- run_turn ----------------------------------------------------------------------------------
async def test_run_turn_parses_fenced_json_and_merges(tmp_path: Path) -> None:
    text = '```json\n{"message": "Set Houston.", "request": "Houston", "values": {"search_city": ["houston"]}, "complete": true}\n```'
    ctx = make_ctx(tmp_path, BASE, [text])
    result = await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])
    assert result.complete and result.message == "Set Houston."
    assert result.draft.values == {"search_city": ["houston"]}
    assert result.draft.request == "Houston"
    system = ctx.ai.calls[0][0]["content"]  # type: ignore[attr-defined]
    assert "## Goal" in system and "| `search_city` |" in system and "Reply format" in system


async def test_run_turn_feeds_errors_back_until_valid(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        BASE,
        ["not json", reply(values={"condition": ["mint"]}), reply(values={"condition": ["new"]})],
    )
    result = await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])
    assert result.draft.values == {"condition": ["new"]}
    calls = ctx.ai.calls  # type: ignore[attr-defined]
    assert "not a JSON object" in calls[1][1]["content"]
    assert "condition" in calls[2][1]["content"].split("# Notes from aimm", 1)[1]


async def test_run_turn_gives_up_after_retries(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE, ["no", "no", "no"])
    with pytest.raises(TurnError, match="couldn't turn that into a valid section"):
        await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])


async def test_run_turn_rejects_secrets_and_unknown_fields(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        BASE,
        [
            reply(values={"password": "hunter2", "colour": "red"}),
            reply(values={"password": "${FACEBOOK_PASSWORD}"}),
        ],
    )
    result = await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])
    assert result.draft.values == {"password": "${FACEBOOK_PASSWORD}"}
    notes = ctx.ai.calls[1][1]["content"]  # type: ignore[attr-defined]
    assert "`password` is secret" in notes and "`colour` is not a field" in notes
    assert "hunter2" not in notes


async def test_run_turn_reports_service_errors_without_the_key(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE, [RuntimeError("401 bad key svcpass_testkey")])
    with pytest.raises(TurnError) as e:
        await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])
    assert "svcpass_testkey" not in str(e.value) and "401" in str(e.value)


# --- the whole conversation ----------------------------------------------------------------------
async def test_new_marketplace_conversation_writes_normalized_file(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        BASE,
        [
            reply("Where do you shop, and how far would you travel?"),
            reply(
                "I set Houston within 40 miles, used items in good condition or better.",
                {
                    "search_city": ["houston"],
                    "radius": [40],
                    "condition": ["used_like_new", "used_good"],
                },
                complete=True,
                request="Search around Houston within 40 miles for good used items.",
            ),
        ],
    )
    ui = ScriptedSetupUI(["Houston, about 40 miles, good used stuff", "yes", "yes"])
    assert await B.converse(ui, ctx, None) == 0

    written = tomllib.loads(ctx.files[0].read_text())
    assert written["marketplace"]["facebook"] == {
        "request": "Search around Houston within 40 miles for good used items.",
        "search_city": ["houston"],
        "radius": [40],
        "condition": ["used_like_new", "used_good"],
    }
    assert written["ai"]["unitysvc"]["api_key"] == "svcpass_testkey"
    assert ui.questions == ["You", "Is this right?", "Write these changes?"]
    assert any("No marketplace is configured yet" in m for m in ui.said())
    # the user's words reached the LLM
    assert "Houston, about 40 miles" in ctx.ai.calls[1][1]["content"]  # type: ignore[attr-defined]
    assert list((tmp_path / "backups").iterdir())


async def test_complete_claim_with_missing_location_goes_back_to_the_llm(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        BASE,
        [
            reply("All set!", {"condition": ["new"]}, complete=True),
            reply("Which city?"),
        ],
    )
    ui = ScriptedSetupUI(["/quit"])
    assert await B.converse(ui, ctx, None) == 0
    second = ctx.ai.calls[1][1]["content"]  # type: ignore[attr-defined]
    assert "Still required: location" in second
    assert ui.questions == ["You"]  # no review was shown


async def test_existing_marketplace_no_at_review_then_change(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        BASE + '\n[marketplace.facebook]\nrequest = "Houston"\nsearch_city = "houston"\n',
        [
            reply("Anything to change?", complete=True, request="Houston"),
            reply(
                "Now shipping too.",
                {"delivery_method": ["all"]},
                complete=True,
                request="Houston, ship or pick up",
            ),
        ],
    )
    ui = ScriptedSetupUI(["facebook", "no", "include shipping", "yes", "no", "/quit"])
    assert await B.converse(ui, ctx, None) == 0
    assert ui.questions == [
        "Update one of these, or create a new marketplace?",
        "Is this right?",
        "What would you like to change?",
        "Is this right?",
        "Write these changes?",
        "What would you like to change?",
    ]
    assert any("Request: Houston" in m for m in ui.said())
    assert "delivery_method" not in ctx.files[0].read_text()  # declined write


async def test_quit_from_the_start_menu(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE + '\n[marketplace.facebook]\nsearch_city = "houston"\n')
    ui = ScriptedSetupUI(["__quit__"])
    assert await B.converse(ui, ctx, None) == 0


async def test_new_name_when_facebook_is_taken(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE + '\n[marketplace.facebook]\nsearch_city = "houston"\n')
    ui = ScriptedSetupUI(["__new__", "bad name", ""])
    draft = await B.choose_target(ui, ctx, None)
    assert draft is not None and draft.name == "facebook_2" and draft.is_new


async def test_show_command_and_turn_errors(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE, [RuntimeError("boom"), reply("Which city?")])
    ui = ScriptedSetupUI(["", "/show", "/quit"])
    assert await B.converse(ui, ctx, None) == 0
    assert any("boom" in m for m in ui.said("error"))
