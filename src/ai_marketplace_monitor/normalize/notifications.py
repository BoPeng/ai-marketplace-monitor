"""Canonical layout for users and [notification.*] sections."""

import json
from dataclasses import fields
from typing import Any, Dict, List, Set, Tuple, Type

from ..channels import section_channel_types, user_channels
from ..config import Config
from ..email_notify import EmailNotificationConfig
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


def _sources(user_raw: Dict[str, Any], notif_raw: Dict[str, Any]) -> List[str]:
    """The enabled sections the user receives, in order, each once."""
    notify_with = user_raw.get("notify_with")
    if notify_with is None:
        names = list(notif_raw)
    else:
        names = [notify_with] if isinstance(notify_with, str) else list(notify_with)
    return list(dict.fromkeys(n for n in names if notif_raw[n].get("enabled") is not False))


def _load_section(content: Dict[str, Any]) -> NotificationConfig:
    instance = NotificationConfig.get_config(name="_", **content)
    if instance is None:
        raise ValueError(f"Unable to determine notification type for {sorted(content)}")
    return instance


def _channels_view(
    user_name: str, user_raw: Dict[str, Any], notif_raw: Dict[str, Any], loaded: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """What a user's channels send (see ``effective.channels_view``)."""
    notifications = {}
    for name, content in notif_raw.items():
        key = _key(content)
        if key not in loaded:
            loaded[key] = _load_section(content)
        notifications[name] = loaded[key]
    user = UserConfig(name=user_name, **user_raw)
    user._channels = user_channels(user, notifications)
    return channels_view(user)


def _key(content: Dict[str, Any]) -> str:
    return json.dumps(content, sort_keys=True, default=str)


def _declares(cls: Type[Any], name: str) -> bool:
    return any(f.name == name for f in fields(cls))


def _holds(content: Dict[str, Any], name: str, value: Any) -> bool:
    """Whether a section with ``content`` loads ``name = value`` unchanged."""
    return bool(getattr(_load_section({**content, name: value}), name) == value)


def _own_channel(user_name: str, user_raw: Dict[str, Any], channel_type: str) -> Dict[str, Any]:
    """A section for a channel the user set up in [user.*].

    It holds the channel fields, and the delivery settings the channel is sent with where a
    section would load others.
    """
    content = {f: user_raw[f] for f in CHANNEL_FIELDS[channel_type] if f in user_raw}
    user = UserConfig(name=user_name, **user_raw)
    baseline = _load_section(content)
    for f in COMMON_FIELDS:
        if not _declares(type(baseline), f):
            continue
        value = getattr(user, f)
        if getattr(baseline, f) != value and _holds(content, f, value):
            content[f] = (
                user_raw[f] if f in user_raw and _holds(content, f, user_raw[f]) else value
            )
    return content


def _new_name(channel_type: str, user_name: str, taken: Set[str]) -> str:
    name = channel_type if channel_type not in taken else f"{channel_type}_{user_name}"
    suffix = 2
    while name in taken:
        name = f"{channel_type}_{user_name}_{suffix}"
        suffix += 1
    return name


def normalize_notifications(cfg: Dict[str, Any], loaded_config: Config) -> None:
    """Rewrite cfg['user'] and cfg['notification'] into canonical form, in place.

    Each user names the sections it receives in ``notify_with``; channels set up in [user.*]
    move into sections (shared by users with the same values); recipients (such as a chat id)
    move from sections to the users who receive them; settings no channel uses are dropped.
    Every step keeps what each user's channels send.
    """
    del loaded_config  # the raw values are compared channel by channel instead
    notif_raw: Dict[str, Any] = cfg.setdefault("notification", {})
    users: Dict[str, Any] = cfg.get("user", {})
    loaded: Dict[str, Any] = {}
    targets = {u: _channels_view(u, raw, notif_raw, loaded) for u, raw in users.items()}

    def same(names: List[str]) -> bool:
        return all(_channels_view(u, users[u], notif_raw, loaded) == targets[u] for u in names)

    for user_raw in users.values():
        user_raw["notify_with"] = _sources(user_raw, notif_raw)
        if isinstance(user_raw.get("digest_with"), str):
            user_raw["digest_with"] = [user_raw["digest_with"]]

    # channels set up in [user.*] become sections
    new: Dict[str, str] = {}
    for user_name, user_raw in users.items():
        received = {
            t
            for n in user_raw["notify_with"]
            for t in section_channel_types(_load_section(notif_raw[n]))
        }
        for channel_type, channel_fields in CHANNEL_FIELDS.items():
            if channel_type in received or not any(f in user_raw for f in channel_fields):
                continue
            content = _own_channel(user_name, user_raw, channel_type)
            key = f"{channel_type}:{_key(content)}"
            if key not in new:
                new[key] = _new_name(channel_type, user_name, set(notif_raw))
                notif_raw[new[key]] = content
            for f in channel_fields:
                user_raw.pop(f, None)
            user_raw["notify_with"].append(new[key])

    # recipients move from a section to the users who receive it
    for name, section in notif_raw.items():
        receivers = [u for u, raw in users.items() if name in raw["notify_with"]]
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
            notif_raw[name] = before_section
            for u, raw in before_users.items():
                users[u] = raw

    # values in [user.*] that no channel uses; recipients (who the user is) stay
    droppable = {*COMMON_FIELDS, *(f for v in CHANNEL_FIELDS.values() for f in v)}
    for user_name, user_raw in users.items():
        for f in [f for f in user_raw if f in droppable and not _is_placeholder(user_raw[f])]:
            value = user_raw.pop(f)
            if not same([user_name]):
                user_raw[f] = value
    for user_name, user_raw in users.items():
        users[user_name] = {
            **{k: v for k, v in user_raw.items() if k not in ("notify_with", "digest_with")},
            "notify_with": user_raw["notify_with"],
            **({"digest_with": user_raw["digest_with"]} if "digest_with" in user_raw else {}),
        }
    if not notif_raw:
        del cfg["notification"]
