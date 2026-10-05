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
from ai_marketplace_monitor.configure.sections import FieldGroup, Outcome, TurnError
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


def test_view_is_the_section_as_written(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    draft = B.view(ctx, "facebook")
    assert not draft.is_new
    assert draft.values == {"search_city": "houston", "radius": 40, "condition": ["used_good"]}
    assert B.missing(ctx, draft) == []


def test_validate_reports_bad_values_and_unknown_names(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE)
    draft = B.view(ctx, "facebook")
    draft.values = {"search_city": ["houston"], "condition": ["mint"]}
    assert "condition" in B.validate(ctx, draft)[0]
    draft.values = {"search_city": ["houston"], "notify": ["bob"], "ai": ["unitysvc"]}
    assert B.validate(ctx, draft) == ["`notify` names ['bob'], which are not in context.users."]
    draft.values = {"search_city": ["houston", "austin"], "radius": [10, 20, 30]}
    assert B.validate(ctx, draft)  # cross-field error found by loading the result


# --- apply ------------------------------------------------------------------------------------
def test_apply_replaces_only_the_marketplace_section(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    draft = B.view(ctx, "facebook")
    draft.values.update({"search_city": "austin", "radius": 25})
    draft.request = "Austin, 25 miles."
    cfg = B.apply(ctx, draft)
    assert cfg["marketplace"]["facebook"] == {
        "request": "Austin, 25 miles.",
        "search_city": "austin",
        "radius": 25,
        "condition": ["used_good"],
    }
    assert cfg["item"] == ctx.user_cfg["item"]  # items inherit; desk keeps dallas
    assert cfg["user"] == ctx.user_cfg["user"]
    assert ctx.user_cfg["marketplace"]["facebook"]["search_city"] == "houston"  # input untouched


def test_describe_says_which_items_keep_their_own_values(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    text = B.describe(ctx, B.view(ctx, "facebook"))
    assert "[marketplace.facebook]" in text
    assert "[item." not in text  # only the marketplace section is shown


async def test_marketplace_default_never_changes_items(tmp_path: Path) -> None:
    # the reported case: a marketplace max_price must not touch [item.example]'s own max_price
    ctx = make_ctx(
        tmp_path,
        ONE_ITEM,
        [
            reply(
                "Max price $1000 for items without their own.",
                {"max_price": "1000"},
                action="save",
                request="Max price $1000 by default.",
                apply_to_all_items=["max_price"],
            )
        ],
    )
    ui = ScriptedSetupUI(["facebook", "yes"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.SAVED
    written = tomllib.loads(ctx.files[0].read_text())
    assert written["marketplace"]["facebook"]["max_price"] == "1000"
    assert written["item"]["example"] == ctx.user_cfg["item"]["example"]
    assert written["item"]["example"]["max_price"] == 300
    diff = next(m for m in ui.said() if m.startswith("```diff"))
    assert "-max_price = 300" not in diff


def test_apply_changes_only_the_marketplace_section(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    draft = B.view(ctx, "facebook")
    draft.values = {"max_price": "1000"}
    cfg = B.apply(ctx, draft)
    assert {k: v for k, v in cfg.items() if k != "marketplace"} == {
        k: v for k, v in ctx.user_cfg.items() if k != "marketplace"
    }


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
    text = '```json\n{"message": "Set Houston.", "request": "Houston", "values": {"search_city": ["houston"]}, "action": "save"}\n```'
    ctx = make_ctx(tmp_path, BASE, [text])
    result = await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])
    assert result.action == "save" and result.message == "Set Houston."
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
                action="save",
                request="Search around Houston within 40 miles for good used items.",
            ),
        ],
    )
    ui = ScriptedSetupUI(["Houston, about 40 miles, good used stuff", "yes"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.SAVED

    written = tomllib.loads(ctx.files[0].read_text())
    assert written["marketplace"]["facebook"] == {
        "request": "Search around Houston within 40 miles for good used items.",
        "search_city": ["houston"],
        "radius": [40],
        "condition": ["used_like_new", "used_good"],
    }
    assert written["ai"]["unitysvc"]["api_key"] == "svcpass_testkey"
    assert ui.questions == ["You", "Write these changes?"]
    assert any("No marketplace is configured yet" in m for m in ui.said())
    # the user's words reached the LLM
    assert "Houston, about 40 miles" in ctx.ai.calls[1][1]["content"]  # type: ignore[attr-defined]
    assert list((tmp_path / "backups").iterdir())


async def test_save_with_missing_location_goes_back_to_the_llm(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        BASE,
        [
            reply("All set!", {"condition": ["new"]}, action="save"),
            reply("Which city?"),
        ],
    )
    ui = ScriptedSetupUI(["/quit"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.CANCELLED
    second = ctx.ai.calls[1][1]["content"]  # type: ignore[attr-defined]
    assert "Still required: location" in second
    assert ui.questions == ["You"]  # no review was shown


async def test_existing_marketplace_change_then_declined_write(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        BASE + '\n[marketplace.facebook]\nrequest = "Houston"\nsearch_city = "houston"\n',
        [
            reply("Anything to change?", request="Houston"),
            reply(
                "Now shipping too.",
                {"delivery_method": ["all"]},
                action="save",
                request="Houston, ship or pick up",
            ),
        ],
    )
    ui = ScriptedSetupUI(["facebook", "include shipping", "no", "/quit"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.CANCELLED
    assert ui.questions == [
        "Update one of these, or create a new marketplace?",
        "You",
        "Write these changes?",
        "What would you like to change?",
    ]
    assert any("Request: Houston" in m for m in ui.said())
    assert "delivery_method" not in ctx.files[0].read_text()  # declined write


async def test_quit_from_the_start_menu(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE + '\n[marketplace.facebook]\nsearch_city = "houston"\n')
    ui = ScriptedSetupUI(["__quit__"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.CANCELLED


async def test_new_name_when_facebook_is_taken(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE + '\n[marketplace.facebook]\nsearch_city = "houston"\n')
    ui = ScriptedSetupUI(["__new__", "bad name", ""])
    draft = await B.choose_target(ui, ctx, None)
    assert draft is not None and draft.name == "facebook_2" and draft.is_new


async def test_show_command_and_turn_errors(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE, [RuntimeError("boom"), reply("Which city?")])
    ui = ScriptedSetupUI(["", "/show", "/quit"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.CANCELLED
    assert any("boom" in m for m in ui.said("error"))


ONE_ITEM = (
    BASE
    + """
[marketplace.facebook]
search_city = "houston"

[item.example]
search_phrases = "road bike"
min_price = 50
max_price = 300
"""
)


async def test_no_goes_to_the_llm_which_decides_to_keep_the_section(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        ONE_ITEM,
        [
            reply("You search Houston. Anything to change?"),
            reply("Okay, I'll keep it as it is.", action="no_change"),
        ],
    )
    before = ctx.files[0].read_text()
    ui = ScriptedSetupUI(["facebook", "no"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.UNCHANGED
    assert len(ctx.ai.calls) == 2  # type: ignore[attr-defined]  # "no" went to the AI
    assert "User: no" in ctx.ai.calls[1][1]["content"]  # type: ignore[attr-defined]
    assert ui.questions == ["Update one of these, or create a new marketplace?", "You"]
    assert "Okay, I'll keep it as it is." in ui.said()
    assert "Nothing was written." in ui.said("success")
    assert ui.said("progress") == ["Thinking...", "Thinking..."]
    assert ctx.ai.timeouts == [llm.TURN_TIMEOUT, llm.TURN_TIMEOUT]  # type: ignore[attr-defined]
    assert ctx.files[0].read_text() == before


async def test_save_without_changes_writes_nothing(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path, ONE_ITEM, [reply("Saving as is.", action="save", request="new summary")]
    )
    before = ctx.files[0].read_text()
    ui = ScriptedSetupUI(["facebook"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.UNCHANGED
    assert "Nothing changed; your config is left as it is." in ui.said("success")
    assert ctx.files[0].read_text() == before


async def test_unknown_action_is_sent_back(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE, [reply(action="finish"), reply("Which city?")])
    result = await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])
    assert result.action == "ask"
    assert "`action` must be one of" in ctx.ai.calls[1][1]["content"]  # type: ignore[attr-defined]


async def test_no_still_goes_to_the_ai_while_something_is_missing(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE, [reply("Which city?"), reply("I need a city to search.")])
    ui = ScriptedSetupUI(["no", "/quit"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.CANCELLED
    assert len(ctx.ai.calls) == 2  # type: ignore[attr-defined]


def test_start_menu_separates_marketplace_and_item_values(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ONE_ITEM)
    text = B._summary(ctx, "facebook")
    assert 'search_city = "houston"' in text
    assert "max_price" not in text.split("```")[1]  # not shown as a marketplace value
    assert "[item." not in text and "(1 item)" in text


class GatewayTimeoutError(Exception):
    status_code = 504


async def test_transient_service_errors_are_retried_once(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path, BASE, [GatewayTimeoutError("504 Gateway time-out"), reply("Which city?")]
    )
    result = await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])
    assert result.message == "Which city?"
    assert len(ctx.ai.calls) == 2  # type: ignore[attr-defined]


async def test_service_failure_offers_retry_with_the_same_message(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        BASE,
        [
            reply("Which city?"),
            GatewayTimeoutError("504"),
            GatewayTimeoutError("504"),
            reply("Austin it is."),
        ],
    )
    ui = ScriptedSetupUI(["Austin", "", "/quit"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.CANCELLED
    assert "Press Enter to try again, or type something else (/quit to stop)" in ui.questions
    last = ctx.ai.calls[-1][1]["content"]  # type: ignore[attr-defined]
    assert last.count("User: Austin") == 1 and "User: \n" not in last


async def test_same_value_in_another_form_is_not_a_change(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path, ONE_ITEM, [reply("Saving.", {"search_city": ["houston"]}, action="save")]
    )
    result = await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])
    assert result.draft.values == {"search_city": "houston"}  # the user's own form is kept
    assert B.same_value("search_city", "austin", ["austin"])
    assert not B.same_value("search_city", "austin", ["dallas"])


def test_llm_sees_only_the_marketplace_section_and_names(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ITEMS)
    draft = B.view(ctx, "facebook")
    prompt = llm.build_messages(B, ctx, draft, [], [])[1]["content"]
    assert '"search_city": "houston"' in prompt
    assert "dallas" not in prompt and "pushbullet_token" not in prompt and "abc" not in prompt
    assert "bike" not in prompt and "sofa" not in prompt  # no items, not even names
    assert '"users": [\n      "me"' in prompt  # names the section may reference


async def test_city_name_is_not_added_to_an_existing_city(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        ONE_ITEM,
        [
            reply(values={"city_name": ["Houston"], "max_price": "1000"}),
            reply(values={"max_price": "1000"}),
        ],
    )
    result = await llm.run_turn(B, ctx, B.view(ctx, "facebook"), [], [])
    assert result.draft.values == {"search_city": "houston", "max_price": "1000"}
    assert "`city_name` may only change" in ctx.ai.calls[1][1]["content"]  # type: ignore[attr-defined]
    draft = B.view(ctx, "facebook")
    draft.values = {"search_city": ["austin"], "city_name": ["Austin"]}
    assert B.validate(ctx, draft) == []  # a new city may bring its name


async def test_builder_writes_refuse_other_sections(tmp_path: Path) -> None:
    from ai_marketplace_monitor.configure.writer import CommitOutcome, commit_sections

    ctx = make_ctx(tmp_path, ITEMS)
    new = B.apply(ctx, B.view(ctx, "facebook"))
    new["item"]["bike"]["max_price"] = "1"  # a change outside the builder's section
    ui = ScriptedSetupUI([])
    outcome = await commit_sections(
        ui, new, ctx.user_cfg, ctx.files, ctx.backup_dir, only=[("marketplace", "facebook")]
    )
    assert outcome is CommitOutcome.FAILED
    assert "Refusing to write" in ui.said("error")[0] and "[item.bike]" in ui.said("error")[0]


async def test_no_change_with_unsaved_changes_goes_back_to_the_llm(tmp_path: Path) -> None:
    # the reported case: max_price set in this conversation, then "no" -> must not be dropped
    ctx = make_ctx(
        tmp_path,
        ONE_ITEM,
        [
            reply("What would you like to change?"),
            reply("Max price set. Anything else?", {"max_price": "1000"}),
            reply("Already 1000, nothing to change.", action="no_change"),
            reply("Saving max price $1000.", action="save", request="Max price $1000."),
        ],
    )
    ui = ScriptedSetupUI(["facebook", "set max price to $1000", "no", "yes"])
    assert (await B.converse(ui, ctx)).outcome is Outcome.SAVED
    third = ctx.ai.calls[3][1]["content"]  # type: ignore[attr-defined]
    assert "There are unsaved changes (max_price: '1000')" in third
    assert (
        tomllib.loads(ctx.files[0].read_text())["marketplace"]["facebook"]["max_price"] == "1000"
    )


def test_situation_separates_saved_and_unsaved_values(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, ONE_ITEM)
    draft = B.view(ctx, "facebook")
    draft.values["max_price"] = "1000"
    prompt = llm.build_messages(B, ctx, draft, [], [])[1]["content"]
    assert '"saved_values": {\n    "search_city": "houston"\n  }' in prompt
    assert '"unsaved_changes": {\n    "max_price": "1000"\n  }' in prompt


@pytest.mark.parametrize(
    "city, ok",
    [
        ("houston", True),
        ("111979382146893", True),
        (["sanfrancisco", "111979382146893"], True),
        ("https://www.facebook.com/marketplace/bogota/search?query=iphone", False),
        ("bogota/search", False),
        ("san francisco", False),
    ],
)
def test_search_city_must_be_a_location_code(tmp_path: Path, city: object, ok: bool) -> None:
    ctx = make_ctx(tmp_path, BASE)
    draft = B.view(ctx, "facebook")
    draft.values = {"search_city": city}
    errors = B.validate(ctx, draft)
    assert (errors == []) is ok
    if not ok:  # the config class's own check, which also explains the URL
        assert "search_city" in errors[0] and "incorrect format" in errors[0]


def test_playbook_explains_url_codes() -> None:
    from ai_marketplace_monitor.configure.playbooks import load_playbook

    text = load_playbook("marketplace").text()
    assert "never guess it" in text and "paste the URL" in text
    assert "`111979382146893`" in text


async def test_initial_request_starts_the_conversation(tmp_path: Path) -> None:
    ctx = make_ctx(
        tmp_path,
        ONE_ITEM,
        [reply("Saving radius 20.", {"radius": 20}, action="save", request="Within 20 miles.")],
    )
    ui = ScriptedSetupUI(["yes"])
    result = await B.converse(ui, ctx, "facebook", request="limit the search to 20 miles")
    assert result.outcome is Outcome.SAVED and result.section == "marketplace.facebook"
    assert result.summary == "Saving radius 20."
    first = ctx.ai.calls[0][1]["content"]  # type: ignore[attr-defined]
    assert "User: limit the search to 20 miles" in first
    assert ui.questions == ["Write these changes?"]  # no menu, no "what to change?"


async def test_quit_returns_to_the_caller(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, BASE, [reply("Which city?")])
    result = await B.converse(ScriptedSetupUI(["/quit"]), ctx, "facebook")
    assert result == build_result(
        "CANCELLED", "marketplace.facebook", "Stopped; nothing was written."
    )


def build_result(outcome: str, section: str, summary: str) -> object:
    from ai_marketplace_monitor.configure.sections import BuildResult

    return BuildResult(Outcome[outcome], section, summary)


async def test_session_reads_config_per_run_and_shows_notes_once(tmp_path: Path) -> None:
    from ai_marketplace_monitor.configure.session import Session
    from tests.configure_util import FakeAI

    config = tmp_path / "config.toml"
    config.write_text(BASE + '\n[user.you]\npushbullet_token = "${AIMM_TEST_UNSET_VAR}"\n')
    session = Session(files=[config], ai=FakeAI([reply("Bye.", action="cancel")] * 2), home=tmp_path)  # type: ignore[arg-type]
    ui = ScriptedSetupUI([])
    first = await B.run(ui, session, "facebook")
    second = await B.run(ui, session, "facebook")
    assert first.outcome is second.outcome is Outcome.CANCELLED
    notes = [m for m in ui.said("warning") if "AIMM_TEST_UNSET_VAR" in m]
    assert len(notes) == 1


async def test_run_reports_an_unreadable_config(tmp_path: Path) -> None:
    from ai_marketplace_monitor.configure.session import Session
    from tests.configure_util import FakeAI

    config = tmp_path / "config.toml"
    config.write_text('[marketplace.facebook]\ncondition = ["mint"]\n')
    ui = ScriptedSetupUI([])
    result = await B.run(ui, Session(files=[config], ai=FakeAI([]), home=tmp_path), "facebook")  # type: ignore[arg-type]
    assert result.outcome is Outcome.FAILED
    assert "Cannot read the configuration" in ui.said("error")[0]
