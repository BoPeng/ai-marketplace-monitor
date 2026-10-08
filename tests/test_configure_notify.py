"""The user and notification toolkits, and a session that sets up both."""

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.configure.agent import run_agent
from ai_marketplace_monitor.configure.flow import _opening, system_prompt
from ai_marketplace_monitor.configure.notify import (
    NOTIFICATION_GUIDES,
    USER_GUIDES,
    NotificationToolkit,
    UserToolkit,
)
from ai_marketplace_monitor.configure.tools import Outcome, ToolExecutor
from ai_marketplace_monitor.normalize.notifications import (
    CHANNEL_FIELDS,
    COMMON_FIELDS,
    RECIPIENT_FIELDS,
)
from tests.configure_util import BASE, FakeModel, make_ws, ui_of

N, U = NotificationToolkit(), UserToolkit()
KITS: Dict[str, Any] = {"notification": N, "user": U}
AI_ONLY = '[ai.unitysvc]\napi_key = "svcpass_testkey"\n'
UNITYSVC_EMAIL = {
    "smtp_server": "smtp.svcpass.com",
    "smtp_username": "smtp-to-mailbox",
    "smtp_password": "${UNITYSVC_API_KEY}",
}


async def ws_for(tmp_path: Path, text: str, answers: Any = None) -> Any:
    return await make_ws(tmp_path, text, answers, toolkits=KITS)


# --- field guides -------------------------------------------------------------------------
def test_notification_guides_cover_channels_and_delivery() -> None:
    channel = {f for fields in CHANNEL_FIELDS.values() for f in fields}
    expected = (channel | set(COMMON_FIELDS) | {"enabled"}) - {"unitysvc_base_url"}
    names = [g.name for g in NOTIFICATION_GUIDES]
    assert sorted(names) == sorted(expected) and len(names) == len(set(names))


def test_user_guides_cover_recipients() -> None:
    expected = set(RECIPIENT_FIELDS) | {
        "notify_with",
        "remind",
        "digest",
        "digest_channels",
        "enabled",
    }
    assert sorted(g.name for g in USER_GUIDES) == sorted(expected)


async def test_completion_rules_name_what_missing_reports(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    completion = ws.playbooks["notification"].body.split("## Completion", 1)[1]
    draft = N.view(ws, "gmail")
    messages = N.missing(ws, draft) + U.missing(ws, U.view(ws, "me"))
    draft.values = {"smtp_password": "${GMAIL_APP_PASSWORD}"}
    ws.draft("user", "me").values = {"notify_with": ["gmail"]}
    messages += N.missing(ws, draft)
    assert len(messages) == 4
    for message in messages:
        assert message.split(":")[0] in completion


# --- what is shown -------------------------------------------------------------------------
async def test_secrets_are_masked_even_in_users(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)  # [user.me] has pushbullet_token inline
    draft = U.view(ws, "me")
    assert U.masked(draft.values) == {"pushbullet_token": "<set; hidden>"}
    assert '"abc"' not in U.describe(draft)


async def test_unitysvc_key_is_offered_as_a_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_fromenv")
    ws = await ws_for(tmp_path, '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n')
    extra = N.show_extra(ws, N.view(ws, "unitysvc"))
    assert extra["unitysvc_api_key"] == "${UNITYSVC_API_KEY} (as in [ai.unitysvc])"
    assert extra["default_user"] == "me" and extra["received_by"] == []
    ws = await ws_for(tmp_path, AI_ONLY)  # the key is written in the file
    extra = N.show_extra(ws, N.view(ws, "unitysvc"))
    assert "svcpass_testkey" not in str(extra) and "UNITYSVC_API_KEY" in extra["unitysvc_api_key"]


# --- completeness ---------------------------------------------------------------------------
async def test_a_notification_needs_a_user_and_its_recipient(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    draft = ws.draft("notification", "gmail")
    assert N.missing(ws, draft)[0].startswith("channel: choose how to notify")
    draft.values = {"smtp_password": "${GMAIL_APP_PASSWORD}"}
    assert N.missing(ws, draft) == [
        "user: no user receives it; add it to `notify_with` of [user.me] (a new section)"
    ]
    user = ws.draft("user", "me")
    user.values = {"notify_with": ["gmail"]}
    assert N.missing(ws, draft) == ["email: [user.me] needs `email` to receive it"]
    assert U.missing(ws, user) == ["email: needed to receive [notification.gmail]"]
    user.values["email"] = "me@gmail.com"
    assert N.missing(ws, draft) == [] and U.missing(ws, user) == []


async def test_unitysvc_email_needs_no_address(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    draft = N.view(ws, "unitysvc_email")
    draft.values = dict(UNITYSVC_EMAIL)
    ws.draft("user", "me").values = {"notify_with": ["unitysvc_email"]}
    assert N.missing(ws, draft) == []


async def test_a_user_without_notify_with_receives_everything(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE + '\n[notification.ntfy]\nntfy_server = "https://ntfy.sh"\n')
    draft = N.view(ws, "ntfy")
    assert N.missing(ws, draft) == ["ntfy_topic: [user.me] needs `ntfy_topic` to receive it"]
    assert N.show_extra(ws, draft)["received_by"] == ["me"]


async def test_a_new_user_must_receive_something(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    [message] = U.missing(ws, U.view(ws, "me"))
    assert message.startswith("notification: [user.me] receives no notification")


# --- checking -------------------------------------------------------------------------------
async def test_validate(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    draft = N.view(ws, "mixed")
    draft.values = {"smtp_password": "${X}", "pushbullet_token": "${Y}"}
    assert "one channel" in N.validate(ws, draft)[0]
    draft.values = {"smtp_port": 99999, "smtp_password": "${X}"}
    assert "smtp_port" in N.validate(ws, draft)[0]
    user = U.view(ws, "me")
    user.values = {"notify_with": ["nope"]}
    assert U.validate(ws, user) == [
        "`notify_with` names ['nope'], which are not in can_reference.notifications."
    ]
    _, problems = N.change(N.view(ws, "gmail"), {"smtp_password": "hunter2"}, [], None)
    assert problems == ["`smtp_password` is secret: only a ${VAR} reference may be set."]


async def test_user_and_notification_drafts_check_together(tmp_path: Path) -> None:
    """A user may name a notification drafted in the same session, and vice versa."""
    ws = await ws_for(tmp_path, AI_ONLY)
    notification = ws.draft("notification", "unitysvc")
    notification.values = {"unitysvc_api_key": "${UNITYSVC_API_KEY}"}
    assert N.validate(ws, notification) == []
    user = ws.draft("user", "me")
    user.values = {"notify_with": ["unitysvc"]}
    assert U.validate(ws, user) == [] and N.validate(ws, notification) == []
    assert N.missing(ws, notification) == [] and U.missing(ws, user) == []


async def test_unset_variables_are_reported_after_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    ws = await ws_for(tmp_path, AI_ONLY)
    draft = N.view(ws, "gmail")
    draft.values = {"smtp_password": "${GMAIL_APP_PASSWORD}"}
    [note] = N.after_save(ws, draft)
    assert "export GMAIL_APP_PASSWORD=<value>" in note
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "x")
    assert N.after_save(ws, draft) == []


# --- the session ---------------------------------------------------------------------------
async def test_start_shows_sections_and_defaults_to_user_me(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    assert await N.choose_target(ws.ui, ws, None) == "*"
    assert "they will go to a new [user.me]" in ui_of(ws).said()[0]
    assert await U.choose_target(ws.ui, ws, None) == "me"
    ws = await ws_for(tmp_path, BASE)
    assert await N.choose_target(ws.ui, ws, "gmail") == "gmail"
    shown = ui_of(ws).said()[0]
    assert "**[user.me]**" in shown and '"abc"' not in shown


async def test_section_guide_reads_users_and_notifications_together(tmp_path: Path) -> None:
    ex = ToolExecutor(await ws_for(tmp_path, AI_ONLY))
    out = await ex.call("section_guide", {"section_type": "notification"})
    assert ex.guides_read == {"notification", "user"}
    assert "[notification.*]" in out["fields"] and "[user.*]" in out["fields"]


async def test_email_session_creates_the_notification_and_user_me(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    monkeypatch.setenv("MY_KEY", "svcpass_mine")
    ws = await ws_for(tmp_path, AI_ONLY, ["notify me by email", "UnitySVC email", "yes"])
    only = [("notification", "*"), *N.companions(ws, "*")]
    executor = ToolExecutor(ws, only=set(only))
    executor.guides_read.update(["notification", "user"])
    model = FakeModel(
        [
            [
                ("section_show", {"section_type": "user", "name": "me"}),
                ("ask_user", {"message": "How would you like to be notified?"}),
            ],
            [("ask_user", {"message": "UnitySVC email or Gmail?"})],
            [
                (
                    "section_update",
                    {
                        "section_type": "notification",
                        "name": "unitysvc_email",
                        "values": UNITYSVC_EMAIL,
                    },
                ),
                (
                    "section_update",
                    {
                        "section_type": "user",
                        "name": "me",
                        "values": '{"notify_with": ["unitysvc_email"]}',
                    },
                ),
                ("save", {"message": "Saving UnitySVC email for [user.me]."}),
            ],
            [("finish", {"message": "Done."})],
        ]
    ).bind(executor.tools_for_model(), lambda: executor.done)
    prompt = system_prompt(ws, ["notification", "user"])
    assert prompt.count("# Task:") == 1  # one playbook for both types
    assert "## Fields of [user.*]" in prompt and "## Fields of [notification.*]" in prompt
    opening = _opening(ws, only)
    assert "[user.me] (new)" in opening and "any [notification.*]" in opening
    assert await run_agent(executor, model, prompt, opening) is Outcome.SAVED
    written = tomllib.loads((tmp_path / "config.toml").read_text())
    assert written["notification"]["unitysvc_email"] == UNITYSVC_EMAIL
    assert written["user"]["me"] == {"notify_with": ["unitysvc_email"]}
    assert ui_of(ws).questions.count("Write these changes?") == 1
    [saved] = model.results("save")
    assert "export UNITYSVC_API_KEY=<value>" in saved["shown_to_user"][0]


async def test_session_cannot_touch_other_section_types(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    executor = ToolExecutor(ws, only={("user", "*"), ("notification", "*")})
    executor.guides_read.update(["notification", "user"])
    ok = await executor.call(
        "section_update",
        {"section_type": "user", "name": "alice", "values": {"email": "a@b.co"}},
    )
    assert ok["ok"], ok
    out = await executor.call("section_show", {"section_type": "marketplace", "name": "x"})
    assert out["ok"] is False


async def test_disabled_sections_do_not_count(tmp_path: Path) -> None:
    ws = await ws_for(
        tmp_path,
        AI_ONLY
        + '\n[notification.ntfy]\nntfy_server = "https://ntfy.sh"\nenabled = false\n'
        + '\n[user.old]\nntfy_topic = "t"\nenabled = false\n',
    )
    assert N.show_extra(ws, N.view(ws, "ntfy"))["received_by"] == []
    assert N.show_extra(ws, N.view(ws, "x"))["default_user"] == "me"
    user = U.view(ws, "me")
    user.values = {"notify_with": ["ntfy"]}
    [message] = U.missing(ws, user)
    assert message.startswith("notification: [user.me] receives no notification")


async def test_an_inline_channel_needs_its_recipient(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    user = U.view(ws, "me")
    user.values = {"smtp_password": "${GMAIL_APP_PASSWORD}"}
    assert U.missing(ws, user) == ["email: needed for the channel set on [user.me]"]


async def test_summary_tells_email_from_phone_notifications(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    assert N.summary(ws, UNITYSVC_EMAIL) == "UnitySVC email with listing photos"
    assert N.summary(ws, {"smtp_password": "${GMAIL_APP_PASSWORD}"}) == "email"
    assert N.summary(ws, {"unitysvc_api_key": "${UNITYSVC_API_KEY}"}) == (
        "UnitySVC phone/chat notifications (text only)"
    )


async def test_playbook_offers_unitysvc_email_for_email(tmp_path: Path) -> None:
    body = (await ws_for(tmp_path, AI_ONLY)).playbooks["notification"].body
    assert 'smtp_username = "smtp-to-mailbox"' in body
    assert "Not for email: use UnitySVC" in body


async def test_email_options_offer_unitysvc_first_then_gmail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    monkeypatch.setenv("MY_KEY", "svcpass_mine")
    ws = await ws_for(tmp_path, '[ai.unitysvc]\napi_key = "${MY_KEY}"\n')
    options = N.show_extra(ws, N.view(ws, "new"))["email_options"]
    assert [o["name"] for o in options] == ["unitysvc_email", "gmail"]
    assert options[0]["values"] == {**UNITYSVC_EMAIL, "smtp_password": "${MY_KEY}"}
    assert "needs" not in options[0]  # the key is already there
    assert "App passwords" in options[1]["needs"]
    # without a UnitySVC key, UnitySVC email says what it needs
    ws = await ws_for(tmp_path, '[user.me]\npushbullet_token = "abc"\n')
    unitysvc = N.show_extra(ws, N.view(ws, "new"))["email_options"][0]
    assert unitysvc["values"]["smtp_password"] == "${UNITYSVC_API_KEY}"
    assert "UNITYSVC_API_KEY" in unitysvc["needs"]
    # a phone/chat channel is already chosen: no email options
    draft = N.view(ws, "unitysvc")
    draft.values = {"unitysvc_api_key": "${UNITYSVC_API_KEY}"}
    assert "email_options" not in N.show_extra(ws, draft)


async def test_playbook_explains_switching_channels(tmp_path: Path) -> None:
    body = (await ws_for(tmp_path, AI_ONLY)).playbooks["notification"].body
    assert "### Switching channels" in body and "instead\nof the old one" in body
