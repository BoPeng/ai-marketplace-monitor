"""Canonical layout for users and their [email.*] and [notification.*] sections."""

import json
from typing import Any, Dict, List, Tuple, Type

from ..channels import user_channels
from ..config import Config
from ..email_notify import EmailNotificationConfig, email_section
from ..notification import (
    CHANNEL,
    COMMON,
    RECIPIENT,
    NotificationConfig,
    PushNotificationConfig,
    fields_with_role,
)
from ..ntfy import NtfyNotificationConfig
from ..pushbullet import PushbulletNotificationConfig
from ..pushover import PushoverNotificationConfig
from ..telegram import TelegramNotificationConfig
from ..unitysvc_notify import UnitySVCNotificationConfig
from ..user import UserConfig
from .effective import channels_view

TYPE_CLASSES: Dict[str, Type[NotificationConfig]] = {
    "email": EmailNotificationConfig,
    "pushbullet": PushbulletNotificationConfig,
    "pushover": PushoverNotificationConfig,
    "ntfy": NtfyNotificationConfig,
    "telegram": TelegramNotificationConfig,
    "unitysvc": UnitySVCNotificationConfig,
}
# field roles, read from the dataclass metadata of the notification classes
COMMON_FIELDS: Tuple[str, ...] = fields_with_role(PushNotificationConfig, COMMON)
RECIPIENT_FIELDS: Tuple[str, ...] = tuple(
    dict.fromkeys(f for cls in TYPE_CLASSES.values() for f in fields_with_role(cls, RECIPIENT))
)
CHANNEL_FIELDS: Dict[str, Tuple[str, ...]] = {
    t: fields_with_role(cls, CHANNEL) for t, cls in TYPE_CLASSES.items()
}


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("${") and value.endswith("}")


def _section_keys(cfg: Dict[str, Any]) -> List[str]:
    return [f"email.{n}" for n in cfg.get("email", {})] + [
        f"notification.{n}" for n in cfg.get("notification", {})
    ]


def _raw(cfg: Dict[str, Any], key: str) -> Dict[str, Any]:
    kind, name = key.split(".", 1)
    return cfg[kind][name]  # type: ignore[no-any-return]


def _sources(user_raw: Dict[str, Any], cfg: Dict[str, Any]) -> List[str]:
    """The enabled sections the user receives, as "email.<name>" and so on, each once."""
    keys = _section_keys(cfg)
    notify_with = user_raw.get("notify_with")
    if notify_with is None:
        names = keys
    else:
        names = [notify_with] if isinstance(notify_with, str) else list(notify_with)
    out = []
    for name in names:
        matches = [name] if name in keys else [k for k in keys if k.split(".", 1)[1] == name]
        out += matches[:1]
    return list(dict.fromkeys(k for k in out if _raw(cfg, k).get("enabled") is not False))


def _load_section(key: str, content: Dict[str, Any]) -> NotificationConfig:
    kind, name = key.split(".", 1)
    if kind == "email":
        return email_section(name, content)
    instance = NotificationConfig.get_config(name=name, **content)
    if instance is None:
        raise ValueError(f"Unable to determine notification type for {sorted(content)}")
    return instance


def _key(content: Dict[str, Any]) -> str:
    return json.dumps(content, sort_keys=True, default=str)


def _channels_view(
    user_name: str, user_raw: Dict[str, Any], cfg: Dict[str, Any], loaded: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """What a user's channels send (see ``effective.channels_view``)."""
    sections = {}
    for key in _section_keys(cfg):
        content = _raw(cfg, key)
        cache_key = f"{key}:{_key(content)}"
        if cache_key not in loaded:
            loaded[cache_key] = _load_section(key, content)
        sections[key] = loaded[cache_key]
    user = UserConfig(name=user_name, **user_raw)
    user._channels = user_channels(user, sections)
    return channels_view(user)


def normalize_notifications(cfg: Dict[str, Any], loaded_config: Config) -> None:
    """Rewrite cfg['user'], cfg['email'] and cfg['notification'] into canonical form.

    Each user names the sections it receives in ``notify_with``, as "email.<name>" and
    "notification.<name>"; recipients (such as a chat id) move from sections to the users
    who receive them; delivery settings in [user.*] that no channel uses are dropped. Every
    step keeps what each user's channels send.
    """
    del loaded_config  # the raw values are compared channel by channel instead
    users: Dict[str, Any] = cfg.get("user", {})
    loaded: Dict[str, Any] = {}
    targets = {u: _channels_view(u, raw, cfg, loaded) for u, raw in users.items()}

    def same(names: List[str]) -> bool:
        return all(_channels_view(u, users[u], cfg, loaded) == targets[u] for u in names)

    for user_raw in users.values():
        user_raw["notify_with"] = _sources(user_raw, cfg)

    # recipients move from a section to the users who receive it
    for key in _section_keys(cfg):
        kind, name = key.split(".", 1)
        section = cfg[kind][name]
        receivers = [u for u, raw in users.items() if key in raw["notify_with"]]
        moved = [f for f in RECIPIENT_FIELDS if f in section]
        if not receivers or not moved:
            continue
        before_section = dict(section)
        before_users = {u: dict(users[u]) for u in receivers}
        for f in moved:
            for u in receivers:
                users[u][f] = section[f]
            del section[f]
        if not same(list(users)):
            cfg[kind][name] = before_section
            for u, raw in before_users.items():
                users[u] = raw

    # delivery settings in [user.*] that no channel uses
    for user_name, user_raw in users.items():
        for f in [f for f in user_raw if f in COMMON_FIELDS and not _is_placeholder(user_raw[f])]:
            value = user_raw.pop(f)
            if not same([user_name]):
                user_raw[f] = value
    for user_name, user_raw in users.items():
        users[user_name] = {
            **{k: v for k, v in user_raw.items() if k != "notify_with"},
            "notify_with": user_raw["notify_with"],
        }
