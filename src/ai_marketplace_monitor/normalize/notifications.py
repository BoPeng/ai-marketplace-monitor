"""Canonical layout for users and [notification.*] sections."""

import json
from dataclasses import fields
from typing import Any, Callable, Dict, List, Set, Tuple, Type

from ..config import Config
from ..email_notify import EmailNotificationConfig
from ..notification import NotificationConfig, PushNotificationConfig
from ..ntfy import NtfyNotificationConfig
from ..pushbullet import PushbulletNotificationConfig
from ..pushover import PushoverNotificationConfig
from ..telegram import TelegramNotificationConfig
from ..user import UserConfig

TYPE_CLASSES: Dict[str, Type[NotificationConfig]] = {
    "email": EmailNotificationConfig,
    "pushbullet": PushbulletNotificationConfig,
    "pushover": PushoverNotificationConfig,
    "ntfy": NtfyNotificationConfig,
    "telegram": TelegramNotificationConfig,
}
_BASE_FIELDS = {"name", "enabled", "request"}
COMMON_FIELDS: Tuple[str, ...] = tuple(
    f.name
    for f in fields(PushNotificationConfig)
    if f.name not in _BASE_FIELDS and not f.name.startswith("_")
)
RECIPIENT_FIELDS: Tuple[str, ...] = (
    "email",
    "telegram_chat_id",
    "pushover_user_key",
    "ntfy_topic",
)
CHANNEL_FIELDS: Dict[str, Tuple[str, ...]] = {
    t: tuple(
        f.name
        for f in fields(cls)
        if f.name not in _BASE_FIELDS
        and f.name not in COMMON_FIELDS
        and f.name not in RECIPIENT_FIELDS
        and not f.name.startswith("_")
    )
    for t, cls in TYPE_CLASSES.items()
}
_USER_KEPT_FIELDS = ("enabled", "request", "remind")
_MERGE_SKIPPED = ("type", "name", "request")


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("${") and value.endswith("}")


def _sources(user_raw: Dict[str, Any], notif_raw: Dict[str, Any]) -> List[str]:
    """Notification sections merged into this user at runtime, in merge order."""
    notify_with = user_raw.get("notify_with")
    if notify_with is None:
        names = list(notif_raw)
    else:
        names = [notify_with] if isinstance(notify_with, str) else list(notify_with)
    return [n for n in names if notif_raw[n].get("enabled") is not False]


def _load_user(content: Dict[str, Any]) -> NotificationConfig:
    return UserConfig(name="_", **content)


def _load_section(content: Dict[str, Any]) -> NotificationConfig:
    instance = NotificationConfig.get_config(name="_", **content)
    if instance is None:
        raise ValueError(f"Unable to determine notification type for {sorted(content)}")
    return instance


def _overridden(
    raw: Dict[str, Any], load: Callable[[Dict[str, Any]], NotificationConfig]
) -> Set[str]:
    """Common fields whose raw value does not change what the source loads to.

    A field is returned when loading the source without it yields the same value as
    loading it with it: either a ``handle_*`` hook replaces the raw value (e.g.
    ``UserConfig``, and any section inferred as one, inherits Pushbullet's
    ``handle_message_format``, which always sets ``"plain_text"``), or the raw value
    equals the default the source would load to anyway (an explicit default). Such a
    value is not a winning raw value and is dropped. Placeholders are exempt (an unset
    variable also loads as if absent).
    """
    present = [f for f in COMMON_FIELDS if f in raw and not _is_placeholder(raw[f])]
    if not present:
        return set()
    full = load(raw)
    return {
        f
        for f in present
        if getattr(full, f) == getattr(load({k: v for k, v in raw.items() if k != f}), f)
    }


def _provenance(
    user_raw: Dict[str, Any],
    sources: List[str],
    notif_raw: Dict[str, Any],
    loaded: Dict[str, NotificationConfig],
) -> Dict[str, Any]:
    """Raw value from the source that wins each field (None when a default wins).

    Mirrors Config.expand_notifications: every non-None field of each source's
    loaded instance, defaults included, overrides what came before. A raw value
    that a load hook replaces counts as a default (see ``_overridden``).
    """
    winners = dict(user_raw)
    for key in _overridden(user_raw, _load_user):
        winners[key] = None
    for name in sources:
        raw = notif_raw[name]
        overridden = _overridden(raw, _load_section)
        for key, value in vars(loaded[name]).items():
            if key in _MERGE_SKIPPED:
                continue
            placeholder = _is_placeholder(raw.get(key)) and winners.get(key) is None
            if value is None and not placeholder:
                continue
            winners[key] = None if key in overridden else raw.get(key)
    return winners


def _declares(cls: Type[Any], name: str) -> bool:
    return any(f.name == name for f in fields(cls))


def _holds(content: Dict[str, Any], name: str, value: Any) -> bool:
    """Whether a section with ``content`` loads ``name = value`` unchanged."""
    return bool(getattr(_load_section({**content, name: value}), name) == value)


def _plan_user(
    user_raw: Dict[str, Any], winners: Dict[str, Any], effective: UserConfig
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], Set[str]]:
    """Canonical user section, per-type channel sections, and forcing section types.

    A section is *forcing* when its loaded class cannot hold the effective value of a
    common field (a hook replaces it, e.g. ``message_format`` on a section inferred as
    ``UserConfig``). The field is then not written there, and the caller merges forcing
    sections first so a non-forcing section re-applies the effective value afterwards.
    """
    user = {k: user_raw[k] for k in _USER_KEPT_FIELDS if k in user_raw}
    user.update({f: winners[f] for f in RECIPIENT_FIELDS if winners.get(f) is not None})
    sections: Dict[str, Dict[str, Any]] = {}
    for section_type, channel_fields in CHANNEL_FIELDS.items():
        content = {f: winners[f] for f in channel_fields if winners.get(f) is not None}
        if content:
            sections[section_type] = content
    # Values a section loads with when a common field is omitted (defaults, including
    # those set by handle_* hooks, e.g. message_format).
    baselines = {t: _load_section(c) for t, c in sections.items()}
    forcing: Set[str] = set()
    for section_type, content in sections.items():
        baseline = baselines[section_type]
        channel_content = dict(content)
        for f in COMMON_FIELDS:
            if not _declares(type(baseline), f):
                continue
            value = getattr(effective, f)
            differs = getattr(baseline, f) != value
            if winners.get(f) is None and not differs:
                continue
            if _holds(channel_content, f, value):
                content[f] = winners[f] if winners.get(f) is not None else value
            elif differs:
                forcing.add(section_type)
    for f in COMMON_FIELDS:
        placed = any(_declares(type(b), f) for b in baselines.values())
        if not placed and winners.get(f) is not None:
            user[f] = winners[f]
    return user, sections, forcing


def _type_owners(sources: List[str], notif_raw: Dict[str, Any]) -> Dict[str, str]:
    """Existing section that supplied the winning channel fields of each type."""
    owners: Dict[str, str] = {}
    for name in sources:
        for section_type, channel_fields in CHANNEL_FIELDS.items():
            if any(f in notif_raw[name] for f in channel_fields):
                owners[section_type] = name
    return owners


def _name_groups(groups: Dict[str, Dict[str, Any]], notif_raw: Dict[str, Any]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    used: Set[str] = set()

    def free(name: str, group: Dict[str, Any]) -> bool:
        return name not in used and (name not in notif_raw or name in group["candidates"])

    for key, group in groups.items():
        base = f"{group['type']}_{group['users'][0]}"
        options = [*group["candidates"], group["type"], base]
        name = next((n for n in options if free(n, group)), None)
        suffix = 2
        while name is None:
            if free(f"{base}_{suffix}", group):
                name = f"{base}_{suffix}"
            suffix += 1
        names[key] = name
        used.add(name)
    return names


def normalize_notifications(cfg: Dict[str, Any], loaded: Config) -> None:
    """Rewrite cfg['user'] and cfg['notification'] into canonical form, in place."""
    notif_raw: Dict[str, Any] = cfg.get("notification", {})
    groups: Dict[str, Dict[str, Any]] = {}
    plans: Dict[str, Tuple[Dict[str, Any], List[str]]] = {}
    for user_name, user_raw in cfg.get("user", {}).items():
        sources = _sources(user_raw, notif_raw)
        winners = _provenance(user_raw, sources, notif_raw, loaded.notification)
        user, sections, forcing = _plan_user(user_raw, winners, loaded.user[user_name])
        owners = _type_owners(sources, notif_raw)
        forcing_keys: List[str] = []
        keys: List[str] = []
        for section_type, content in sections.items():
            key = f"{section_type}:{json.dumps(content, sort_keys=True, default=str)}"
            group = groups.setdefault(
                key, {"type": section_type, "content": content, "users": [], "candidates": []}
            )
            group["users"].append(user_name)
            owner = owners.get(section_type)
            if owner is not None and owner not in group["candidates"]:
                group["candidates"].append(owner)
            (forcing_keys if section_type in forcing else keys).append(key)
        # Forcing sections merge first; each group stays in the fixed type order.
        plans[user_name] = (user, forcing_keys + keys)

    names = _name_groups(groups, notif_raw)
    claimed = {name: key for key, name in names.items()}
    new_notifs: Dict[str, Any] = {}
    for name, raw in notif_raw.items():
        if name in claimed:
            kept = {k: raw[k] for k in ("request", "enabled") if k in raw}
            new_notifs[name] = {**kept, **groups[claimed[name]]["content"]}
        else:
            new_notifs[name] = raw
    for key, name in names.items():
        new_notifs.setdefault(name, groups[key]["content"])

    cfg["user"] = {
        u: {**user, "notify_with": [names[k] for k in keys]} for u, (user, keys) in plans.items()
    }
    if new_notifs:
        cfg["notification"] = new_notifs
