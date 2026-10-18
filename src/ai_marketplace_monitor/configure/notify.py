"""The user, email and notification toolkits: who is notified (`[user.*]`) and how.

They are configured together. An `[email.*]` section sends aimm's full email (its server and
credentials; `[email.unitysvc]` and `[email.gmail]` start from a preset), a
`[notification.*]` section one phone or chat channel; either may send the daily digest
(`digest_at`). A `[user.*]` section holds where the user receives them (email address, chat
ID, ...) and which sections it receives (`notify_with`, all of them when unset).
"""

from __future__ import annotations

import asyncio
import copy
import os
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from ..config_toml import dump_config_toml
from ..email_notify import (
    EMAIL_PRESETS,
    UNITYSVC_SMTP_SERVER,
    UNITYSVC_SMTP_USERNAME,
    EmailNotificationConfig,
    email_section,
)
from ..normalize import NormalizeError, expand
from ..normalize.notifications import CHANNEL_FIELDS, RECIPIENT_FIELDS, TYPE_CLASSES
from ..notification import TEST_TIMEOUT, NotificationConfig
from ..ntfy import NtfyNotificationConfig
from ..pushbullet import PushbulletNotificationConfig
from ..pushover import PushoverNotificationConfig
from ..telegram import TelegramNotificationConfig
from ..unitysvc_notify import UnitySVCNotificationConfig
from ..user import UserConfig
from .marketplace import _plain
from .toolkits import FieldGuide, SectionDraft, Toolkit, is_reference, unset_variable_notes
from .ui import SetupUI

if TYPE_CHECKING:
    from .workspace import Workspace

EMAIL_FIELDS = {*CHANNEL_FIELDS["email"], "email"}

_DIGEST_AT = (
    "local time of a daily digest of the last 24 hours (searches, matches and rejected "
    "listings of every item) sent by this section; it uses AI tokens, one short AI call per "
    "item with new activity to summarize it"
)
_COMMON_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide("max_retries", "rarely needed: attempts to send a message", "integer", "5"),
    FieldGuide("retry_delay", "rarely needed: seconds between attempts", "integer", "60"),
    FieldGuide(
        "rate_limit_enabled",
        "rarely needed: throttle sending",
        "`true` or `false`",
        "off (on for Telegram)",
    ),
    FieldGuide("instance_rate_limit", "rarely needed: seconds between messages", "number", "1"),
    FieldGuide("global_rate_limit", "rarely needed: messages per second", "integer", "10"),
    FieldGuide("enabled", "only to turn this section off without removing it", "`false`", "on"),
)

EMAIL_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "smtp_username",
        "[email.unitysvc] (required): the UnitySVC service that delivers it "
        "(`smtp-to-mailbox` sends to the address registered with UnitySVC; a relay service "
        "sends elsewhere); [email.gmail]: the Gmail address; other servers: the login",
        '`"smtp-to-mailbox"` for UnitySVC, or e.g. `"me@gmail.com"`',
        "required for [email.unitysvc]; otherwise the user's email",
    ),
    FieldGuide(
        "smtp_password",
        "[email.unitysvc]: the UnitySVC API key (preset `${UNITYSVC_API_KEY}`); "
        "[email.gmail]: a Gmail app password (preset `${GMAIL_SMTP_PASSWORD}`); other "
        "servers: required",
        '`"${UNITYSVC_API_KEY}"`, `"${GMAIL_SMTP_PASSWORD}"` or another reference',
        "preset for [email.unitysvc] and [email.gmail]; otherwise required",
        secret=True,
    ),
    FieldGuide(
        "smtp_server",
        "only for an email section other than [email.unitysvc] and [email.gmail] (preset), "
        "and only if it cannot be worked out from the user's address",
        'e.g. `"smtp.office365.com"`',
        "preset, or derived from the user's email address",
    ),
    FieldGuide("smtp_port", "only if the provider requires another port", "`587`", "587 (preset)"),
    FieldGuide(
        "smtp_from", "only if the sender address must differ", "an email address", "the login"
    ),
    FieldGuide(
        "digest_at", _DIGEST_AT + ": the full digest, with the listings", '`"08:00"`', "no digest"
    ),
    *_COMMON_GUIDES,
)

NOTIFICATION_GUIDES: Tuple[FieldGuide, ...] = (
    # UnitySVC
    FieldGuide(
        "unitysvc_api_key",
        "UnitySVC phone/chat notifications (Discord, Slack, SMS, push; not email, which is "
        "[email.unitysvc]): the UnitySVC API key (the same key as UnitySVC AI)",
        '`"${UNITYSVC_API_KEY}"`',
        "required for UnitySVC",
        secret=True,
    ),
    FieldGuide(
        "unitysvc_service",
        "UnitySVC: only to send to one service instead of the user's saved destination",
        'a service path, e.g. `"labs/msg-to-discord"`',
        "`notify`: the UnitySVC inbox and the destination saved in UnitySVC",
    ),
    # push services
    FieldGuide(
        "pushbullet_token",
        "Pushbullet: the access token from pushbullet.com, Settings, Account",
        '`"${PUSHBULLET_TOKEN}"`',
        "required for Pushbullet",
        secret=True,
    ),
    FieldGuide("pushbullet_proxy_type", "Pushbullet: only behind a proxy", '`"https"`', "none"),
    FieldGuide(
        "pushbullet_proxy_server",
        "Pushbullet: only behind a proxy",
        '`"proxy.example.com:8080"`',
        "none",
    ),
    FieldGuide(
        "pushover_api_token",
        "Pushover: the API token of an application the user creates at pushover.net",
        '`"${PUSHOVER_API_TOKEN}"`',
        "required for Pushover",
        secret=True,
    ),
    FieldGuide(
        "ntfy_server",
        "ntfy: the server",
        '`"https://ntfy.sh"` or a self-hosted URL',
        "required for ntfy",
    ),
    FieldGuide(
        "telegram_token",
        "Telegram: the bot token from @BotFather",
        '`"${TELEGRAM_TOKEN}"`',
        "required for Telegram",
        secret=True,
    ),
    FieldGuide(
        "with_description",
        "include the listing description: all of it, none, or the first N characters",
        "`true`, `false` or a number, e.g. `200`",
        "no description",
    ),
    FieldGuide(
        "message_format",
        "how messages are formatted",
        '`"plain_text"` or `"markdown"`',
        '`"plain_text"`',
    ),
    FieldGuide(
        "digest_at",
        _DIGEST_AT + ": a short version; leave it out when the user gets the digest by email",
        '`"08:00"`',
        "no digest",
    ),
    *_COMMON_GUIDES,
)

USER_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "email",
        "email: where the user receives it; not needed for [email.unitysvc], which sends to "
        "the address registered with UnitySVC",
        '`"me@gmail.com"` or a list',
        "no email",
    ),
    FieldGuide(
        "pushover_user_key",
        "Pushover: the user key on the user's pushover.net dashboard",
        '`"${PUSHOVER_USER_KEY}"`',
        "required for Pushover",
        secret=True,
    ),
    FieldGuide(
        "ntfy_topic",
        "ntfy: the topic the user subscribes to in the ntfy app; anyone who knows it can read "
        "it, so make it hard to guess",
        'e.g. `"aimm-7f3k2q"`',
        "required for ntfy",
    ),
    FieldGuide(
        "telegram_chat_id",
        "Telegram: the user's chat ID (from @userinfobot)",
        '`"123456789"`',
        "required for Telegram",
    ),
    FieldGuide(
        "notify_with",
        "the [email.*] and [notification.*] sections this user receives",
        'e.g. `["email.unitysvc", "notification.unitysvc"]`',
        "every enabled email and notification section",
    ),
    FieldGuide(
        "remind",
        "remind the user about a listing that is still available after this long",
        '`"1 day"`, `"2 days"` or `false`',
        "no reminders",
    ),
    FieldGuide("enabled", "only to stop notifying this user", "`false`", "on"),
)

SECRETS = {g.name for g in EMAIL_GUIDES + NOTIFICATION_GUIDES + USER_GUIDES if g.secret}
_LABELS = {
    "email": "email",
    "unitysvc": "UnitySVC",
    "pushbullet": "Pushbullet",
    "pushover": "Pushover",
    "ntfy": "ntfy",
    "telegram": "Telegram",
}


# --- facts shared by the toolkits ------------------------------------------------------------
SENDERS = ("email", "notification")  # the section types that send


@dataclass
class _PushFields(
    PushbulletNotificationConfig,
    PushoverNotificationConfig,
    NtfyNotificationConfig,
    TelegramNotificationConfig,
    UnitySVCNotificationConfig,
):
    """Every field a [notification.*] section can have, to read its values."""


def _names(ws: "Workspace", section_type: str) -> List[str]:
    """Saved sections of a type, then the ones drafted in this session."""
    names = list(ws.user_cfg.get(section_type, {}))
    return names + [n for t, n in ws.drafts if t == section_type and n not in names]


def _active(ws: "Workspace", section_type: str, name: str) -> Dict[str, Any] | None:
    """A section's values, or None if it does not exist or is disabled (aimm skips it)."""
    values = ws.section(section_type, name)
    return None if values is None or values.get("enabled") is False else values


def default_user(ws: "Workspace") -> str:
    """The user notifications go to: the first enabled user, or a new ``[user.me]``."""
    users = [n for n in _names(ws, "user") if _active(ws, "user", n) is not None]
    return users[0] if users else "me"


def sender_keys(ws: "Workspace") -> List[str]:
    """The sections that send, as "email.<name>" and "notification.<name>"."""
    return [f"{t}.{n}" for t in SENDERS for n in _names(ws, t)]


def resolve(ws: "Workspace", entry: str) -> str | None:
    """The section a ``notify_with`` entry names: a bare name is the one kind that has it."""
    keys = sender_keys(ws)
    if entry in keys:
        return entry
    matches = [k for k in keys if k.split(".", 1)[1] == entry]
    return matches[0] if len(matches) == 1 else None


def sender_values(ws: "Workspace", key: str) -> Dict[str, Any]:
    """A sending section's values; an email section's with its preset's under them."""
    kind, name = key.split(".", 1)
    values = ws.section(kind, name) or {}
    return {**EMAIL_PRESETS.get(name, {}), **values} if kind == "email" else values


def channel_types(values: Dict[str, Any]) -> List[str]:
    """The channel types of a [notification.*] section whose fields are set (one, if valid)."""
    return [
        t
        for t, names in CHANNEL_FIELDS.items()
        if t != "email" and any(values.get(f) for f in names)
    ]


def sender_types(ws: "Workspace", key: str) -> List[str]:
    """The channel types a sending section sets up."""
    if key.startswith("email."):
        return ["email"]
    return channel_types(sender_values(ws, key))


def _listed(value: Any) -> List[str]:
    return [value] if isinstance(value, str) else list(value or [])


def received(ws: "Workspace", values: Dict[str, Any]) -> List[str]:
    """Enabled sections a user with these values receives, as "email.<name>" and so on."""
    if "notify_with" in values:
        keys = [resolve(ws, e) for e in _listed(values["notify_with"])]
    else:
        keys = list(sender_keys(ws))
    return [
        k
        for k in dict.fromkeys(k for k in keys if k is not None)
        if _active(ws, *k.split(".", 1)) is not None
    ]


def receivers(ws: "Workspace", key: str) -> List[str]:
    """Enabled users who receive a section ("email.<name>" or "notification.<name>")."""
    return [
        user
        for user in _names(ws, "user")
        if (values := _active(ws, "user", user)) is not None and key in received(ws, values)
    ]


def missing_recipients(ws: "Workspace", key: str, user: Dict[str, Any]) -> List[str]:
    """Recipient fields (email, chat ID, ...) a user needs to receive a section."""
    values = sender_values(ws, key)
    out = []
    for kind in sender_types(ws, key):
        if kind == "email" and str(values.get("smtp_server", "")).lower() == UNITYSVC_SMTP_SERVER:
            continue  # UnitySVC delivers to the address registered with it
        for f in TYPE_CLASSES[kind].required_fields:
            if f in RECIPIENT_FIELDS and not user.get(f) and not values.get(f):
                out.append(f)
    return out


def notified_via(ws: "Workspace", values: Dict[str, Any]) -> List[str]:
    """Channels that reach a user with these values, with the recipient fields they need."""
    kinds: List[str] = []
    for key in received(ws, values):
        if not missing_recipients(ws, key, values):
            kinds += sender_types(ws, key)
    return list(dict.fromkeys(kinds))


# fields whose change is worth a test message: where the user receives, and from which sections
_TESTED_USER_FIELDS = {"notify_with", *RECIPIENT_FIELDS}


def _unset_variables(sections: List[Dict[str, Any]]) -> List[str]:
    """Variables of ``${VAR}`` references in these sections that are not set here."""
    names = []
    for section in sections:
        for value in section.values():
            for v in value if isinstance(value, list) else [value]:
                if is_reference(v) and v[2:-1] not in os.environ:
                    names.append(v[2:-1])
    return list(dict.fromkeys(names))


class _NotifyToolkit(Toolkit):
    """What users and their email and notification sections have in common."""

    playbook = "notification"

    def field_names(self: "_NotifyToolkit") -> List[str]:
        return [g.name for g in self.guides]

    def masked(self: "_NotifyToolkit", values: Dict[str, Any]) -> Dict[str, Any]:
        return {
            k: v if k not in SECRETS or is_reference(v) else "<set; hidden>"
            for k, v in values.items()
        }

    def view(self: "_NotifyToolkit", ws: "Workspace", name: str) -> SectionDraft:
        section = ws.user_cfg.get(self.section_type, {}).get(name)
        values = {k: copy.deepcopy(v) for k, v in (section or {}).items() if k != "request"}
        return SectionDraft(
            section_type=self.section_type,
            name=name,
            is_new=section is None,
            request=(section or {}).get("request"),
            values=values,
            original=copy.deepcopy(values),
            original_request=(section or {}).get("request"),
        )

    def context(self: "_NotifyToolkit", ws: "Workspace") -> Dict[str, List[str]]:
        return {
            "users": _names(ws, "user"),
            "emails": _names(ws, "email"),
            "notifications": _names(ws, "notification"),
        }

    def show_extra(self: "_NotifyToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        return {"default_user": default_user(ws), "unitysvc_api_key": _unitysvc_key(ws)}

    def companions(self: "_NotifyToolkit", ws: "Workspace", name: str) -> List[Tuple[str, str]]:
        return [("user", default_user(ws)), ("user", "*"), ("email", "*"), ("notification", "*")]

    def describe(self: "_NotifyToolkit", draft: SectionDraft) -> str:
        section = {"request": draft.request} if draft.request else {}
        section.update(self.masked(draft.values))
        return f"```toml\n{dump_config_toml({self.section_type: {draft.name: section}})}```"

    def after_save(self: "_NotifyToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        return unset_variable_notes(draft)

    def _loads_with_others(
        self: "_NotifyToolkit", ws: "Workspace", draft: SectionDraft
    ) -> List[str]:
        """The whole config, with this session's other drafts, must still load."""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                expand(
                    self.apply(ws.config_with_drafts(exclude=draft.key), draft),
                    ws.system_cfg,
                    partial=True,
                )
        except NormalizeError as e:
            return [str(e)]
        return []

    def _test_plan(
        self: "_NotifyToolkit", ws: "Workspace", name: str
    ) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        """What a test of this section sends.

        Returns the config to load, the users to send to, and the sections the test reads.
        """
        raise NotImplementedError

    async def send_test(self: "_NotifyToolkit", ws: "Workspace", name: str) -> Dict[str, Any]:
        """Send a test message through the saved section's channels, to the users who get it.

        One attempt per channel; nothing is written to the cache or the config.
        """
        from ..config import Config

        label = f"[{self.section_type}.{name}]"
        cfg, user_names, sections = self._test_plan(ws, name)
        if not user_names:
            return {"ok": False, "errors": [f"No enabled user receives {label}."]}
        unset = _unset_variables(sections)
        if unset:
            return {
                "ok": True,
                "sent": False,
                "can_run_here": False,
                "reason": (
                    f"{label} uses environment variables that are not set where aimm "
                    f"configure runs: {', '.join(unset)}, so a test here would fail for that "
                    "reason alone. Set them and test again; if aimm runs elsewhere (e.g. in "
                    "Docker), use Send test in the Settings of aimm's web UI, which runs with "
                    "aimm's own environment."
                ),
            }
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                users = Config.from_dicts(ws.system_cfg, cfg, partial=True).user
        except Exception as e:
            return {"ok": False, "errors": [f"The configuration does not load: {e}"]}
        await ws.ui.say(f"Sending a test message through {label}...")
        results = []
        for user in user_names:
            for r in await asyncio.to_thread(
                NotificationConfig.test_all, users[user], timeout=TEST_TIMEOUT
            ):
                results.append({"user": user, "channel": r.channel, "ok": r.ok, "error": r.error})
        if not results:
            return {"ok": False, "errors": [f"{label} has no channel that can send yet."]}
        lines = [
            f"{'✓' if r['ok'] else '✗'} {r['channel']} to [user.{r['user']}]"
            + ("" if r["ok"] else f": {r['error']}")
            for r in results
        ]
        failed = not all(r["ok"] for r in results)
        await ws.ui.say("\n".join(lines), kind="warning" if failed else "info")
        return {
            "ok": True,
            "sent": True,
            "results": results,
            "note": (
                "aimm showed these results to the user. Explain them in a sentence; for a "
                "failure, say what the error likely means and offer a fix (e.g. another token "
                "or another channel)."
            ),
        }

    async def choose_target(
        self: "_NotifyToolkit", ui: SetupUI, ws: "Workspace", name: str | None
    ) -> str | None:
        """Show users and their sections (masked); any of them may change in this session."""
        sections = [
            (t, n, s)
            for t in ("user", *SENDERS)
            for n, s in ws.user_cfg.get(t, {}).items()
            if isinstance(s, dict)
        ]
        if sections:
            body = "\n\n".join(
                f"**[{t}.{n}]**\n\n```toml\n"
                f"{dump_config_toml({t: {n: _NOTIFY_KITS[t].masked(s)}})}```"
                for t, n, s in sections
            )
            await ui.say(f"Users, email and notifications:\n\n{body}", markdown=True)
        else:
            await ui.say("No notification is set up yet; they will go to a new [user.me].")
        if name is not None:
            return name
        return default_user(ws) if self.section_type == "user" else "*"


def email_options(ws: "Workspace") -> List[Dict[str, Any]]:
    """Ways to send aimm's email, UnitySVC first, with the section and values to write."""
    key = _unitysvc_key(ws)
    reference = key.split(" ")[0] if key and key.startswith("${") else "${UNITYSVC_API_KEY}"
    unitysvc: Dict[str, Any] = {
        "option": "UnitySVC email",
        "section": "email.unitysvc",
        # the preset has the server and ${UNITYSVC_API_KEY}; the service shows where it goes
        "values": {
            "smtp_username": UNITYSVC_SMTP_USERNAME,
            **({} if reference == "${UNITYSVC_API_KEY}" else {"smtp_password": reference}),
        },
        "about": "aimm's full email with listing photos, sent to the email address registered "
        "with the user's UnitySVC account; no `email` on the user and no app password needed. "
        "To send elsewhere through a UnitySVC relay service, set its name as smtp_username",
    }
    if key is None:
        unitysvc["needs"] = "a UnitySVC API key (unitysvc.com), set as UNITYSVC_API_KEY"
    gmail = {
        "option": "Gmail",
        "section": "email.gmail",
        "values": {"smtp_username": "<the Gmail address>"},
        "user_needs": "`email`: where the user receives it (often the same Gmail address)",
        "about": "aimm's full email with listing photos, sent from the user's Gmail; the preset "
        "has the server and the password reference ${GMAIL_SMTP_PASSWORD}",
        "needs": "a Gmail app password: in their Google account, turn on 2-Step Verification, "
        "then Security, App passwords; create one for aimm and set it as GMAIL_SMTP_PASSWORD",
    }
    other = {
        "option": "Another email account",
        "section": "email.<provider>, e.g. email.outlook",
        "values": {
            "smtp_server": "<the provider's SMTP server>",
            "smtp_username": "<the login>",
            "smtp_password": "${<PROVIDER>_SMTP_PASSWORD}",
        },
        "user_needs": "`email`: where the user receives it",
    }
    return [unitysvc, gmail, other]


def _unitysvc_key(ws: "Workspace") -> str | None:
    """How a section can reference the user's UnitySVC key (never the key itself)."""
    for name, section in ws.user_cfg.get("ai", {}).items():
        if not isinstance(section, dict) or section.get("provider", name) != "unitysvc":
            continue
        key = section.get("api_key")
        if is_reference(key):
            return f"{key} (as in [ai.{name}])"
        if key:
            return (
                f"[ai.{name}] has the key written in the file; ask the user to set it as "
                "UNITYSVC_API_KEY in their environment and use ${UNITYSVC_API_KEY}"
            )
    if "UNITYSVC_API_KEY" in os.environ:
        return "${UNITYSVC_API_KEY} (set in the environment)"
    return None


class _SenderToolkit(_NotifyToolkit):
    """An [email.*] or [notification.*] section: what sends, to the users who receive it."""

    def _key(self: "_SenderToolkit", name: str) -> str:
        return f"{self.section_type}.{name}"

    def _channel_missing(self: "_SenderToolkit", name: str, values: Dict[str, Any]) -> List[str]:
        raise NotImplementedError

    def missing(self: "_SenderToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        key = self._key(draft.name)
        out = self._channel_missing(draft.name, draft.values)
        users = receivers(ws, key)
        if not users:
            user = default_user(ws)
            state = "" if ws.section("user", user) is not None else " (a new section)"
            out.append(
                f"user: no user receives it; add {key} to `notify_with` of [user.{user}]{state}"
            )
        for user in users:
            values = ws.section("user", user) or {}
            out += [
                f"{f}: [user.{user}] needs `{f}` to receive it"
                for f in missing_recipients(ws, key, values)
            ]
        return out

    def testable(self: "_SenderToolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        return not self._channel_missing(draft.name, draft.values) and (
            draft.values.get("enabled") is not False
        )

    def _test_plan(
        self: "_SenderToolkit", ws: "Workspace", name: str
    ) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        """This section only, to each user who receives it."""
        key = self._key(name)
        cfg = copy.deepcopy(ws.user_cfg)
        users = receivers(ws, key)
        for user in users:
            cfg["user"][user]["notify_with"] = [key]
        return cfg, users, [sender_values(ws, key), *(cfg["user"][u] for u in users)]

    def can_apply(self: "_SenderToolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        # a channel without its user yet is still part of the config the user's checks see
        return not self._channel_missing(draft.name, draft.values)

    def show_extra(self: "_SenderToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        return {
            "received_by": receivers(ws, self._key(draft.name)),
            **super().show_extra(ws, draft),
        }


class EmailToolkit(_SenderToolkit):
    section_type = "email"
    guides = EMAIL_GUIDES
    config_class = EmailNotificationConfig

    def summary(self: "EmailToolkit", ws: "Workspace", values: Dict[str, Any]) -> str | None:
        return "email with listing photos" + (
            f", daily digest at {values['digest_at']}" if values.get("digest_at") else ""
        )

    def show_extra(self: "EmailToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        extra = super().show_extra(ws, draft)
        preset = EMAIL_PRESETS.get(draft.name)
        if preset:
            extra["preset"] = preset  # values the section has unless it sets them
        else:
            extra["email_options"] = email_options(ws)
        return extra

    def _channel_missing(self: "EmailToolkit", name: str, values: Dict[str, Any]) -> List[str]:
        merged = {**EMAIL_PRESETS.get(name, {}), **values}
        out = [] if merged.get("smtp_password") else ["smtp_password: required to send email"]
        if name == "unitysvc" and not values.get("smtp_username"):
            out.append(
                f"smtp_username: the UnitySVC service that delivers it ({UNITYSVC_SMTP_USERNAME} "
                "to the address registered with UnitySVC, or a relay service)"
            )
        return out

    def validate(self: "EmailToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                email_section(draft.name, draft.values)
        except Exception as e:
            return [_plain(e)]
        return self._loads_with_others(ws, draft)


class NotificationToolkit(_SenderToolkit):
    section_type = "notification"
    guides = NOTIFICATION_GUIDES
    config_class = _PushFields

    def summary(
        self: "NotificationToolkit", ws: "Workspace", values: Dict[str, Any]
    ) -> str | None:
        labels = {"unitysvc": "UnitySVC phone/chat notifications (text only)"}
        kinds = ", ".join(labels.get(t, _LABELS[t]) for t in channel_types(values))
        if kinds and values.get("digest_at"):
            kinds += f", daily digest at {values['digest_at']}"
        return kinds or None

    def show_extra(
        self: "NotificationToolkit", ws: "Workspace", draft: SectionDraft
    ) -> Dict[str, Any]:
        kinds = channel_types(draft.values)
        return {
            "channel": _LABELS[kinds[0]] if len(kinds) == 1 else None,
            **super().show_extra(ws, draft),
        }

    def _channel_missing(
        self: "NotificationToolkit", name: str, values: Dict[str, Any]
    ) -> List[str]:
        kinds = channel_types(values)
        if not kinds:
            return [
                (
                    "channel: choose how to notify (UnitySVC, Pushbullet, Pushover, ntfy or "
                    "Telegram; email is an [email.*] section) and set its fields"
                )
            ]
        return [
            f"{f}: required for {_LABELS[kind]}"
            for kind in kinds
            for f in TYPE_CLASSES[kind].required_fields
            if f in CHANNEL_FIELDS[kind] and not values.get(f)
        ]

    def validate(self: "NotificationToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        if not draft.values:
            return []
        email = sorted(k for k in draft.values if k in EMAIL_FIELDS)
        if email:
            return [
                (
                    f"{', '.join(email)}: email is sent by an [email.*] section (e.g. email.unitysvc "
                    "or email.gmail), not [notification.*]."
                )
            ]
        kinds = channel_types(draft.values)
        if len(kinds) > 1:
            labels = ", ".join(_LABELS[k] for k in kinds)
            return [
                (
                    f"A [notification.*] section is one channel, but these fields are for {labels}: "
                    "use one section per channel."
                )
            ]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                config = NotificationConfig.get_config(name=draft.name, **draft.values)
        except Exception as e:
            return [_plain(e)]
        if config is None:
            return ["These fields do not belong to one notification channel."]
        return self._loads_with_others(ws, draft)


class UserToolkit(_NotifyToolkit):
    section_type = "user"
    guides = USER_GUIDES
    config_class = UserConfig

    def summary(self: "UserToolkit", ws: "Workspace", values: Dict[str, Any]) -> str | None:
        via = notified_via(ws, values)
        return f"notified via {', '.join(via)}" if via else "not notified"

    def show_extra(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        return {"receives": received(ws, draft.values), **super().show_extra(ws, draft)}

    def validate(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        misplaced = sorted(
            k
            for k in draft.values
            if k == "digest_at" or any(k in fs for fs in CHANNEL_FIELDS.values())
        )
        if misplaced:
            return [
                (
                    f"{', '.join(misplaced)}: how messages are sent, and the digest, belong in an "
                    "[email.*] or [notification.*] section; a user only says where it receives "
                    "them and which sections (`notify_with`)."
                )
            ]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                UserConfig(name=draft.name, **draft.values)
        except Exception as e:
            return [_plain(e)]
        unknown = [n for n in _listed(draft.values.get("notify_with")) if resolve(ws, n) is None]
        if unknown:
            return [
                (
                    f"`notify_with` names {unknown}, which are not sections in "
                    "can_reference.emails (as email.<name>) or can_reference.notifications (as "
                    "notification.<name>)."
                )
            ]
        return self._loads_with_others(ws, draft)

    def missing(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        keys = received(ws, draft.values)
        if not keys:
            return [
                (
                    f"notification: [user.{draft.name}] receives nothing; set up an [email.*] or "
                    "[notification.*] section and add it to `notify_with`"
                )
            ]
        out = []
        for key in keys:
            out += [
                f"{f}: needed to receive [{key}]"
                for f in missing_recipients(ws, key, draft.values)
            ]
        return out

    def testable(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        changed = set(draft.unsaved_changes()) & _TESTED_USER_FIELDS
        return bool(changed) and draft.values.get("enabled") is not False

    def _test_plan(
        self: "UserToolkit", ws: "Workspace", name: str
    ) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        """Every channel of the user."""
        values = _active(ws, "user", name)
        if values is None:
            return ws.user_cfg, [], []
        sections = [sender_values(ws, k) for k in received(ws, values)]
        return ws.user_cfg, [name], [values, *sections]

    def can_apply(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        # only with sections that are part of the config too
        if not draft.values:
            return False
        ready = {f"{t}.{n}" for t in SENDERS for n in ws.user_cfg.get(t, {})}
        for key, other in ws.drafts.items():
            kit = ws.toolkits.get(key[0])
            if key[0] in SENDERS and kit is not None and kit.can_apply(ws, other):
                ready.add(f"{key[0]}.{key[1]}")
        return all(resolve(ws, n) in ready for n in _listed(draft.values.get("notify_with")))


_NOTIFY_KITS: Dict[str, _NotifyToolkit] = {
    "user": UserToolkit(),
    "email": EmailToolkit(),
    "notification": NotificationToolkit(),
}
