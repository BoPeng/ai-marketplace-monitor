"""The user, email and notification toolkits, and a session that sets them up."""

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
    EMAIL_GUIDES,
    NOTIFICATION_GUIDES,
    USER_GUIDES,
    EmailToolkit,
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

E, N, U = EmailToolkit(), NotificationToolkit(), UserToolkit()
KITS: Dict[str, Any] = {"email": E, "notification": N, "user": U}
AI_ONLY = '[ai.unitysvc]\napi_key = "svcpass_testkey"\n'
DELIVERY = {"max_retries", "retry_delay", "rate_limit_enabled", "instance_rate_limit"}


async def ws_for(tmp_path: Path, text: str, answers: Any = None) -> Any:
    return await make_ws(tmp_path, text, answers, toolkits=KITS)


# --- field guides -------------------------------------------------------------------------
def test_notification_guides_cover_push_channels_and_delivery() -> None:
    channel = {f for t, fields in CHANNEL_FIELDS.items() if t != "email" for f in fields}
    expected = (channel | set(COMMON_FIELDS) | {"enabled", "digest_at"}) - {"unitysvc_base_url"}
    names = [g.name for g in NOTIFICATION_GUIDES]
    assert sorted(names) == sorted(expected) and len(names) == len(set(names))


def test_email_guides_cover_smtp_and_the_digest() -> None:
    names = {g.name for g in EMAIL_GUIDES}
    assert set(CHANNEL_FIELDS["email"]) <= names and {"digest_at", "enabled"} <= names
    assert DELIVERY <= names and "message_format" not in names


def test_user_guides_cover_recipients_only() -> None:
    expected = set(RECIPIENT_FIELDS) | {"notify_with", "remind", "enabled"}
    assert sorted(g.name for g in USER_GUIDES) == sorted(expected)


async def test_completion_rules_name_what_missing_reports(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    completion = ws.playbooks["notification"].body.split("## Completion", 1)[1]
    draft = N.view(ws, "pushover")
    messages = N.missing(ws, draft) + U.missing(ws, U.view(ws, "me"))
    draft.values = {"pushover_api_token": "${PUSHOVER_API_TOKEN}"}
    ws.draft("user", "me").values = {"notify_with": ["notification.pushover"]}
    messages += N.missing(ws, draft)
    assert len(messages) == 4
    for message in messages:
        assert message.split(":")[0] in completion


# --- what is shown -------------------------------------------------------------------------
async def test_secrets_are_masked(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft = N.view(ws, "pushbullet")
    assert N.masked(draft.values) == {"pushbullet_token": "<set; hidden>"}
    assert '"abc"' not in N.describe(draft)


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


async def test_a_preset_email_section_shows_its_preset(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    extra = E.show_extra(ws, E.view(ws, "gmail"))
    assert extra["preset"]["smtp_server"] == "smtp.gmail.com"
    assert "email_options" not in extra
    assert "email_options" in E.show_extra(ws, E.view(ws, "work"))


# --- completeness ---------------------------------------------------------------------------
async def test_a_notification_needs_a_user_and_its_recipient(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    draft = ws.draft("notification", "tg")
    assert N.missing(ws, draft)[0].startswith("channel: choose how to notify")
    draft.values = {"telegram_token": "${TELEGRAM_TOKEN}"}
    assert N.missing(ws, draft) == [
        "user: no user receives it; add notification.tg to `notify_with` of [user.me] "
        "(a new section)"
    ]
    user = ws.draft("user", "me")
    user.values = {"notify_with": ["notification.tg"]}
    assert N.missing(ws, draft) == [
        "telegram_chat_id: [user.me] needs `telegram_chat_id` to receive it"
    ]
    assert U.missing(ws, user) == ["telegram_chat_id: needed to receive [notification.tg]"]
    user.values["telegram_chat_id"] = "123"
    assert N.missing(ws, draft) == [] and U.missing(ws, user) == []


async def test_a_gmail_section_needs_the_users_address(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    draft = ws.draft("email", "gmail")
    draft.values = {"smtp_username": "me@gmail.com"}  # the preset has the password reference
    user = ws.draft("user", "me")
    user.values = {"notify_with": ["gmail"]}  # a bare name: the one email.gmail
    assert E.missing(ws, draft) == ["email: [user.me] needs `email` to receive it"]
    user.values["email"] = "me@gmail.com"
    assert E.missing(ws, draft) == []


async def test_unitysvc_email_needs_no_address(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    draft = ws.draft("email", "unitysvc")
    draft.values = {"smtp_username": "smtp-to-mailbox"}  # the rest is the preset's
    ws.draft("user", "me").values = {"notify_with": ["email.unitysvc"]}
    assert E.missing(ws, draft) == []
    assert E.can_apply(ws, draft)


async def test_a_user_without_notify_with_receives_everything(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE + '\n[notification.ntfy]\nntfy_server = "https://ntfy.sh"\n')
    draft = N.view(ws, "ntfy")
    assert N.missing(ws, draft) == ["ntfy_topic: [user.me] needs `ntfy_topic` to receive it"]
    assert N.show_extra(ws, draft)["received_by"] == ["me"]


async def test_a_new_user_must_receive_something(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    [message] = U.missing(ws, U.view(ws, "me"))
    assert message.startswith("notification: [user.me] receives nothing")


# --- checking -------------------------------------------------------------------------------
async def test_validate(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    draft = N.view(ws, "mixed")
    draft.values = {"telegram_token": "${X}", "pushbullet_token": "${Y}"}
    assert "one channel" in N.validate(ws, draft)[0]
    draft.values = {"smtp_password": "${X}"}
    assert "email is sent by an [email.*] section" in N.validate(ws, draft)[0]
    email = E.view(ws, "work")
    email.values = {"smtp_port": 99999, "smtp_password": "${X}"}
    assert "smtp_port" in E.validate(ws, email)[0]
    email.values = {"pushbullet_token": "${X}"}
    assert "no option pushbullet_token" in E.validate(ws, email)[0]
    user = U.view(ws, "me")
    user.values = {"notify_with": ["nope"]}
    assert "`notify_with` names ['nope']" in U.validate(ws, user)[0]
    user.values = {"pushbullet_token": "${X}"}
    assert "belong in an [email.*] or [notification.*] section" in U.validate(ws, user)[0]
    user.values = {"digest_at": "08:00"}
    assert U.validate(ws, user)[0].startswith("digest_at:")
    _, problems = E.change(E.view(ws, "gmail"), {"smtp_password": "hunter2"}, [], None)
    assert problems == ["`smtp_password` is secret: only a ${VAR} reference may be set."]


async def test_user_and_section_drafts_check_together(tmp_path: Path) -> None:
    """A user may name a section drafted in the same session, and vice versa."""
    ws = await ws_for(tmp_path, AI_ONLY)
    notification = ws.draft("notification", "unitysvc")
    notification.values = {"unitysvc_api_key": "${UNITYSVC_API_KEY}"}
    email = ws.draft("email", "unitysvc")
    email.values = {"smtp_username": "smtp-to-mailbox", "digest_at": "08:00"}
    assert N.validate(ws, notification) == [] and E.validate(ws, email) == []
    user = ws.draft("user", "me")
    user.values = {"notify_with": ["notification.unitysvc", "email.unitysvc"]}
    assert U.validate(ws, user) == [] and N.validate(ws, notification) == []
    assert N.missing(ws, notification) == [] and U.missing(ws, user) == []
    assert U.can_apply(ws, user)


async def test_unset_variables_are_reported_after_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GMAIL_SMTP_PASSWORD", raising=False)
    ws = await ws_for(tmp_path, AI_ONLY)
    draft = E.view(ws, "work")
    draft.values = {"smtp_server": "smtp.example.com", "smtp_password": "${GMAIL_SMTP_PASSWORD}"}
    [note] = E.after_save(ws, draft)
    assert "export GMAIL_SMTP_PASSWORD=<value>" in note
    monkeypatch.setenv("GMAIL_SMTP_PASSWORD", "x")
    assert E.after_save(ws, draft) == []


# --- the session ---------------------------------------------------------------------------
async def test_start_shows_sections_and_defaults_to_user_me(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    assert await N.choose_target(ws.ui, ws, None) == "*"
    assert "they will go to a new [user.me]" in ui_of(ws).said()[0]
    assert await U.choose_target(ws.ui, ws, None) == "me"
    ws = await ws_for(tmp_path, BASE)
    assert await N.choose_target(ws.ui, ws, "gmail") == "gmail"
    shown = ui_of(ws).said()[0]
    assert "**[user.me]**" in shown and "**[notification.pushbullet]**" in shown
    assert '"abc"' not in shown


async def test_section_guide_reads_users_and_their_sections_together(tmp_path: Path) -> None:
    ex = ToolExecutor(await ws_for(tmp_path, AI_ONLY))
    out = await ex.call("section_guide", {"section_type": "email"})
    assert ex.guides_read == {"email", "notification", "user"}
    for section in ("[email.*]", "[notification.*]", "[user.*]"):
        assert section in out["fields"]


async def test_email_session_creates_the_email_section_and_user_me(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    ws = await ws_for(tmp_path, AI_ONLY, ["notify me by email", "UnitySVC email", "yes"])
    only = [("email", "*"), *E.companions(ws, "*")]
    executor = ToolExecutor(ws, only=set(only))
    executor.guides_read.update(["email", "notification", "user"])
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
                        "section_type": "email",
                        "name": "unitysvc",
                        "values": {"smtp_username": "smtp-to-mailbox", "digest_at": "08:00"},
                    },
                ),
                (
                    "section_update",
                    {
                        "section_type": "user",
                        "name": "me",
                        "values": '{"notify_with": ["email.unitysvc"]}',
                    },
                ),
                ("save", {"message": "Saving UnitySVC email for [user.me]."}),
            ],
            [("finish", {"message": "Done."})],
        ]
    ).bind(executor.tools_for_model(), lambda: executor.done)
    prompt = system_prompt(ws, ["email", "notification", "user"])
    assert prompt.count("# Task:") == 1  # one playbook for the three types
    assert "## Fields of [user.*]" in prompt and "## Fields of [email.*]" in prompt
    opening = _opening(ws, only)
    assert "[user.me] (new)" in opening and "any [email.*]" in opening
    assert await run_agent(executor, model, prompt, opening) is Outcome.SAVED
    written = tomllib.loads((tmp_path / "config.toml").read_text())
    assert written["email"]["unitysvc"] == {
        "smtp_username": "smtp-to-mailbox",
        "digest_at": "08:00",
    }
    assert ui_of(ws).questions.count("Write these changes?") == 1


async def test_session_cannot_touch_other_section_types(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    executor = ToolExecutor(ws, only={("user", "*"), ("email", "*"), ("notification", "*")})
    executor.guides_read.update(["email", "notification", "user"])
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
    user.values = {"notify_with": ["notification.ntfy"]}
    [message] = U.missing(ws, user)
    assert message.startswith("notification: [user.me] receives nothing")


async def test_summaries(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, AI_ONLY)
    assert E.summary(ws, {}) == "email with listing photos"
    assert E.summary(ws, {"digest_at": "08:00"}) == (
        "email with listing photos, daily digest at 08:00"
    )
    assert N.summary(ws, {"unitysvc_api_key": "${UNITYSVC_API_KEY}"}) == (
        "UnitySVC phone/chat notifications (text only)"
    )


async def test_playbook_offers_unitysvc_email_for_email(tmp_path: Path) -> None:
    body = (await ws_for(tmp_path, AI_ONLY)).playbooks["notification"].body
    assert '`[email.unitysvc]` with `smtp_username = "smtp-to-mailbox"`' in body
    assert "Not for email: that is\n  `[email.unitysvc]`" in body


async def test_email_options_offer_unitysvc_first_then_gmail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    monkeypatch.setenv("MY_KEY", "svcpass_mine")
    ws = await ws_for(tmp_path, '[ai.unitysvc]\napi_key = "${MY_KEY}"\n')
    options = E.show_extra(ws, E.view(ws, "new"))["email_options"]
    assert [o["section"] for o in options][:2] == ["email.unitysvc", "email.gmail"]
    assert options[0]["values"] == {
        "smtp_username": "smtp-to-mailbox",
        "smtp_password": "${MY_KEY}",
    }
    assert "needs" not in options[0]  # the key is already there
    assert "App passwords" in options[1]["needs"]
    # without a UnitySVC key, UnitySVC email says what it needs; the preset has the reference
    ws = await ws_for(tmp_path, "[user.me]\n")
    unitysvc = E.show_extra(ws, E.view(ws, "new"))["email_options"][0]
    assert unitysvc["values"] == {"smtp_username": "smtp-to-mailbox"}
    assert "UNITYSVC_API_KEY" in unitysvc["needs"]


async def test_playbook_explains_switching_channels(tmp_path: Path) -> None:
    body = (await ws_for(tmp_path, AI_ONLY)).playbooks["notification"].body
    assert "### Switching channels" in body and "instead\nof the old one" in body
    assert "### The daily digest" in body
