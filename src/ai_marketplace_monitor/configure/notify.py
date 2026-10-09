"""The user and notification toolkits: who is notified (`[user.*]`) and how (`[notification.*]`).

They are configured together. A `[notification.*]` section holds one channel (its servers and
credentials); a `[user.*]` section holds where the user receives it (email address, chat ID,
...) and which notifications it receives (`notify_with`, all of them when unset).
"""

from __future__ import annotations

import asyncio
import copy
import os
import warnings
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from ..config_toml import dump_config_toml
from ..email_notify import UNITYSVC_SMTP_SERVER, UNITYSVC_SMTP_USERNAME
from ..normalize import NormalizeError, expand
from ..normalize.notifications import CHANNEL_FIELDS, RECIPIENT_FIELDS, TYPE_CLASSES
from ..notification import TEST_TIMEOUT, NotificationConfig
from ..user import UserConfig
from .marketplace import _plain
from .toolkits import FieldGuide, SectionDraft, Toolkit, is_reference, unset_variable_notes
from .ui import SetupUI

if TYPE_CHECKING:
    from .workspace import Workspace

NOTIFICATION_GUIDES: Tuple[FieldGuide, ...] = (
    # email
    FieldGuide(
        "smtp_server",
        "email: `smtp.svcpass.com` for UnitySVC email; otherwise only if it cannot be worked "
        "out from the user's address (Gmail, Outlook and most providers can)",
        '`"smtp.svcpass.com"`, or e.g. `"smtp.gmail.com"`',
        "derived from the user's email address",
    ),
    FieldGuide("smtp_port", "email: only if the provider requires another port", "`587`", "587"),
    FieldGuide(
        "smtp_username",
        "email: `smtp-to-mailbox` for smtp.svcpass.com (write it); otherwise only if it differs "
        "from the user's address",
        '`"smtp-to-mailbox"` for UnitySVC email, or a login name',
        "the user's email (`smtp-to-mailbox` for smtp.svcpass.com)",
    ),
    FieldGuide(
        "smtp_password",
        "email: a Gmail app password, or the UnitySVC API key for smtp.svcpass.com",
        '`"${GMAIL_APP_PASSWORD}"` or `"${UNITYSVC_API_KEY}"`',
        "required for email",
        secret=True,
    ),
    FieldGuide(
        "smtp_from",
        "email: only if the sender address must differ",
        "an email address",
        "the SMTP username",
    ),
    # UnitySVC
    FieldGuide(
        "unitysvc_api_key",
        "UnitySVC phone/chat notifications (Discord, Slack, SMS, push; not email, which uses "
        "smtp.svcpass.com): the UnitySVC API key (the same key as UnitySVC AI)",
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
    # every channel
    FieldGuide(
        "with_description",
        "include the listing description: all of it, none, or the first N characters",
        "`true`, `false` or a number, e.g. `200`",
        "no description",
    ),
    FieldGuide(
        "message_format",
        "push channels: how messages are formatted",
        '`"plain_text"`, `"markdown"` or `"html"`',
        '`"plain_text"`',
    ),
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
    FieldGuide("enabled", "only to turn this channel off without removing it", "`false`", "on"),
)

USER_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "email",
        "email: where the user receives it; not needed for smtp.svcpass.com, which sends to "
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
        "the [notification.*] sections this user receives",
        'list of notification names, e.g. `["gmail"]`',
        "every enabled notification",
    ),
    FieldGuide(
        "remind",
        "remind the user about a listing that is still available after this long",
        '`"1 day"`, `"2 days"` or `false`',
        "no reminders",
    ),
    FieldGuide(
        "digest_at",
        "local time of a daily digest of the last 24 hours (searches, matches and rejected "
        "listings of every item): the full digest by email, a short one on push channels",
        '`"08:00"`',
        "no digest",
    ),
    FieldGuide(
        "digest_with",
        "the [notification.*] sections, among those the user receives, that send the digest",
        'list of notification names, e.g. `["gmail"]`',
        "every notification the user receives",
    ),
    FieldGuide(
        "digest_summary",
        "an AI-written summary of each item in the digest (what looks promising, what sold, "
        "the best bet), one short AI call per item per day",
        "`false` to turn it off",
        "on",
    ),
    FieldGuide("enabled", "only to stop notifying this user", "`false`", "on"),
)

SECRETS = {g.name for g in NOTIFICATION_GUIDES + USER_GUIDES if g.secret}
_LABELS = {
    "email": "email",
    "unitysvc": "UnitySVC",
    "pushbullet": "Pushbullet",
    "pushover": "Pushover",
    "ntfy": "ntfy",
    "telegram": "Telegram",
}


# --- facts shared by both toolkits -----------------------------------------------------------
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


def channel_types(values: Dict[str, Any]) -> List[str]:
    """The channel types whose fields are set (one, for a valid notification)."""
    return [t for t, names in CHANNEL_FIELDS.items() if any(values.get(f) for f in names)]


def _listed(value: Any) -> List[str]:
    return [value] if isinstance(value, str) else list(value or [])


def receivers(ws: "Workspace", notification: str) -> List[str]:
    """Users who receive a notification: it is in their notify_with, or that is unset."""
    out = []
    for user in _names(ws, "user"):
        values = _active(ws, "user", user)
        if values is None:
            continue
        if "notify_with" not in values or notification in _listed(values["notify_with"]):
            out.append(user)
    return out


def received(ws: "Workspace", values: Dict[str, Any]) -> List[str]:
    """Enabled notifications a user with these values receives."""
    if "notify_with" in values:
        disabled = [
            n
            for n in _names(ws, "notification")
            if (ws.section("notification", n) or {}).get("enabled") is False
        ]
        return [n for n in _listed(values["notify_with"]) if n not in disabled]
    return [n for n in _names(ws, "notification") if _active(ws, "notification", n) is not None]


def notified_via(ws: "Workspace", values: Dict[str, Any]) -> List[str]:
    """Channels that reach a user with these values, with the recipient fields they need.

    A channel counts if it is set on the user itself or on a notification the user receives.
    """
    kinds = channel_types(values) if not missing_recipients(values, values) else []
    for name in received(ws, values):
        notification = ws.section("notification", name) or {}
        if not missing_recipients(notification, values):
            kinds += channel_types(notification)
    return list(dict.fromkeys(kinds))


def missing_recipients(notification: Dict[str, Any], user: Dict[str, Any]) -> List[str]:
    """Recipient fields (email, chat ID, ...) a user needs to receive a notification."""
    out = []
    for kind in channel_types(notification):
        if kind == "email" and str(notification.get("smtp_server", "")).lower() == (
            UNITYSVC_SMTP_SERVER
        ):
            continue  # UnitySVC delivers to the address registered with it
        for f in TYPE_CLASSES[kind].required_fields:
            if f in RECIPIENT_FIELDS and not user.get(f) and not notification.get(f):
                out.append(f)
    return out


# fields whose change is worth a test message: the user's channels and where they receive them
_TESTED_USER_FIELDS = {
    "notify_with",
    *RECIPIENT_FIELDS,
    *(f for names in CHANNEL_FIELDS.values() for f in names),
}


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
    """What users and notifications have in common."""

    playbook = "notification"
    config_class = UserConfig  # a user holds every notification field

    def field_names(self: "_NotifyToolkit") -> List[str]:
        return [g.name for g in self.guides]

    def masked(self: "_NotifyToolkit", values: Dict[str, Any]) -> Dict[str, Any]:
        # secrets of either kind: an older config may keep a token in [user.*]
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
        return {"users": _names(ws, "user"), "notifications": _names(ws, "notification")}

    def show_extra(self: "_NotifyToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        return {"default_user": default_user(ws), "unitysvc_api_key": _unitysvc_key(ws)}

    def companions(self: "_NotifyToolkit", ws: "Workspace", name: str) -> List[Tuple[str, str]]:
        return [("user", default_user(ws)), ("user", "*"), ("notification", "*")]

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
    ) -> Tuple[Dict[str, Any], List[str] | None, List[str], List[Dict[str, Any]]]:
        """What a test of this section sends.

        Returns the config to load, the channels to test (None: all), the users to send to,
        and the sections the test reads.
        """
        raise NotImplementedError

    async def send_test(self: "_NotifyToolkit", ws: "Workspace", name: str) -> Dict[str, Any]:
        """Send a test message through the saved section's channels, to the users who get it.

        One attempt per channel; nothing is written to the cache or the config.
        """
        from ..config import Config

        label = f"[{self.section_type}.{name}]"
        cfg, channels, user_names, sections = self._test_plan(ws, name)
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
                NotificationConfig.test_all, users[user], channels=channels, timeout=TEST_TIMEOUT
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
        """Show users and notifications (masked); any of them may change in this session."""
        sections = [
            (t, n, s)
            for t in ("user", "notification")
            for n, s in ws.user_cfg.get(t, {}).items()
            if isinstance(s, dict)
        ]
        if sections:
            body = "\n\n".join(
                f"**[{t}.{n}]**\n\n```toml\n"
                f"{dump_config_toml({t: {n: _NOTIFY_KITS[t].masked(s)}})}```"
                for t, n, s in sections
            )
            await ui.say(f"Users and notifications:\n\n{body}", markdown=True)
        else:
            await ui.say("No notification is set up yet; they will go to a new [user.me].")
        if name is not None:
            return name
        return default_user(ws) if self.section_type == "user" else "*"


def email_options(ws: "Workspace") -> List[Dict[str, Any]]:
    """Ways to send aimm's email, UnitySVC first, with the values to write."""
    key = _unitysvc_key(ws)
    reference = key.split(" ")[0] if key and key.startswith("${") else "${UNITYSVC_API_KEY}"
    unitysvc = {
        "option": "UnitySVC email",
        "name": "unitysvc_email",
        "values": {
            "smtp_server": UNITYSVC_SMTP_SERVER,
            "smtp_username": UNITYSVC_SMTP_USERNAME,
            "smtp_password": reference,
        },
        "about": "aimm's full email with listing photos, sent to the email address registered "
        "with the user's UnitySVC account; no `email` on the user and no app password needed",
    }
    if key is None:
        unitysvc["needs"] = "a UnitySVC API key (unitysvc.com), set as UNITYSVC_API_KEY"
    gmail = {
        "option": "Gmail",
        "name": "gmail",
        "values": {"smtp_password": "${GMAIL_APP_PASSWORD}"},
        "user_needs": "`email`: the Gmail address, on the user",
        "about": "aimm's full email with listing photos, sent from and to the user's Gmail",
        "needs": "a Gmail app password: in their Google account, turn on 2-Step Verification, "
        "then Security, App passwords; create one for aimm and set it as GMAIL_APP_PASSWORD",
    }
    return [unitysvc, gmail]


def _unitysvc_key(ws: "Workspace") -> str | None:
    """How a notification can reference the user's UnitySVC key (never the key itself)."""
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


class NotificationToolkit(_NotifyToolkit):
    section_type = "notification"
    guides = NOTIFICATION_GUIDES

    def summary(
        self: "NotificationToolkit", ws: "Workspace", values: Dict[str, Any]
    ) -> str | None:
        unitysvc_email = str(values.get("smtp_server", "")).lower() == UNITYSVC_SMTP_SERVER
        labels = {
            "email": "UnitySVC email with listing photos" if unitysvc_email else "email",
            "unitysvc": "UnitySVC phone/chat notifications (text only)",
        }
        return ", ".join(labels.get(t, t) for t in channel_types(values)) or None

    def show_extra(
        self: "NotificationToolkit", ws: "Workspace", draft: SectionDraft
    ) -> Dict[str, Any]:
        kinds = channel_types(draft.values)
        extra = {
            "channel": _LABELS[kinds[0]] if len(kinds) == 1 else None,
            "received_by": receivers(ws, draft.name),
            **super().show_extra(ws, draft),
        }
        if kinds in ([], ["email"]):  # still choosing, or choosing how to email
            extra["email_options"] = email_options(ws)
        return extra

    def _channel_missing(self: "NotificationToolkit", values: Dict[str, Any]) -> List[str]:
        kinds = channel_types(values)
        if not kinds:
            return [
                (
                    "channel: choose how to notify (email, UnitySVC, Pushbullet, Pushover, ntfy or "
                    "Telegram) and set its fields"
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

    def missing(self: "NotificationToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        out = self._channel_missing(draft.values)
        users = receivers(ws, draft.name)
        if not users:
            user = default_user(ws)
            state = "" if ws.section("user", user) is not None else " (a new section)"
            out.append(
                f"user: no user receives it; add it to `notify_with` of [user.{user}]{state}"
            )
        for user in users:
            values = ws.section("user", user) or {}
            out += [
                f"{f}: [user.{user}] needs `{f}` to receive it"
                for f in missing_recipients(draft.values, values)
            ]
        return out

    def testable(self: "NotificationToolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        return bool(channel_types(draft.values)) and draft.values.get("enabled") is not False

    def _test_plan(
        self: "NotificationToolkit", ws: "Workspace", name: str
    ) -> Tuple[Dict[str, Any], List[str] | None, List[str], List[Dict[str, Any]]]:
        """This notification only, to each user who receives it."""
        values = ws.section("notification", name) or {}
        cfg = copy.deepcopy(ws.user_cfg)
        users = receivers(ws, name)
        for user in users:
            cfg["user"][user]["notify_with"] = [name]
        return cfg, channel_types(values), users, [values, *(cfg["user"][u] for u in users)]

    def can_apply(self: "NotificationToolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        # a channel without its user yet is still part of the config the user's checks see
        return bool(draft.values) and not self._channel_missing(draft.values)


class UserToolkit(_NotifyToolkit):
    section_type = "user"
    guides = USER_GUIDES

    def summary(self: "UserToolkit", ws: "Workspace", values: Dict[str, Any]) -> str | None:
        via = notified_via(ws, values)
        return f"notified via {', '.join(via)}" if via else "not notified"

    def show_extra(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        return {"receives": received(ws, draft.values), **super().show_extra(ws, draft)}

    def validate(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                UserConfig(name=draft.name, **draft.values)
        except Exception as e:
            return [_plain(e)]
        known = _names(ws, "notification")
        unknown = [n for n in _listed(draft.values.get("notify_with")) if n not in known]
        if unknown:
            return [
                f"`notify_with` names {unknown}, which are not in can_reference.notifications."
            ]
        receives = received(ws, draft.values)
        unreceived = [n for n in _listed(draft.values.get("digest_with")) if n not in receives]
        if unreceived:
            return [
                (
                    f"`digest_with` names {unreceived}, which are not notifications this user "
                    f"receives ({receives})."
                )
            ]
        return self._loads_with_others(ws, draft)

    def missing(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        names = received(ws, draft.values)
        inline = any(draft.values.get(f) for fs in CHANNEL_FIELDS.values() for f in fs)
        if not names and not inline:
            return [
                (
                    f"notification: [user.{draft.name}] receives no notification; set one up "
                    "([notification.*]) and add it to `notify_with`"
                )
            ]
        # a channel set on the user itself (an older layout) needs its recipient too
        out = [
            f"{f}: needed for the channel set on [user.{draft.name}]"
            for f in missing_recipients(draft.values, draft.values)
        ]
        for name in names:
            values = ws.section("notification", name) or {}
            out += [
                f"{f}: needed to receive [notification.{name}]"
                for f in missing_recipients(values, draft.values)
            ]
        return out

    def testable(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        changed = set(draft.unsaved_changes()) & _TESTED_USER_FIELDS
        return bool(changed) and draft.values.get("enabled") is not False

    def _test_plan(
        self: "UserToolkit", ws: "Workspace", name: str
    ) -> Tuple[Dict[str, Any], List[str] | None, List[str], List[Dict[str, Any]]]:
        """Every channel of the user."""
        values = _active(ws, "user", name)
        if values is None:
            return ws.user_cfg, None, [], []
        notifications = [ws.section("notification", n) or {} for n in received(ws, values)]
        return ws.user_cfg, None, [name], [values, *notifications]

    def can_apply(self: "UserToolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        # only with notifications that are part of the config too
        if not draft.values:
            return False
        kit = ws.toolkits.get("notification")
        ready = set(ws.user_cfg.get("notification", {}))
        for key, other in ws.drafts.items():
            if key[0] == "notification" and kit is not None and kit.can_apply(ws, other):
                ready.add(key[1])
        return all(n in ready for n in _listed(draft.values.get("notify_with")))


_NOTIFY_KITS: Dict[str, _NotifyToolkit] = {
    "user": UserToolkit(),
    "notification": NotificationToolkit(),
}
