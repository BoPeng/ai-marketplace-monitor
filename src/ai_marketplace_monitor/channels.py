"""The channels a user is notified through: one for each section the user receives.

A user receives the [email.*] and [notification.*] sections named in ``notify_with`` (every
enabled one when it is unset). Each section sends on its own, with the user's values (who
receives: ``email``, ``telegram_chat_id``, ...) under the section's: a user can receive two
email sections, or two Telegram bots. Alerts, the digest (from the sections with a
``digest_at``) and test messages all go through these channels.
"""

from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Tuple, Type

if TYPE_CHECKING:
    from .notification import NotificationConfig


@dataclass(frozen=True)
class Channel:
    """One way a user is notified."""

    # the section, as "email.<name>" or "notification.<name>", with " (<type>)" for a
    # notification section of several channel types
    name: str
    # the section, as "email.<name>" or "notification.<name>"
    section: str
    config: "NotificationConfig"
    # other sections the user receives that send the same message, sent once through this one
    also: Tuple[str, ...] = ()

    @property
    def sections(self: "Channel") -> Tuple[str, ...]:
        """The sections this channel sends for."""
        return (self.section, *self.also)

    @property
    def label(self: "Channel") -> str:
        """How the channel is shown."""
        return self.name


def channel_classes() -> Dict[str, Type["NotificationConfig"]]:
    from .email_notify import EmailNotificationConfig
    from .ntfy import NtfyNotificationConfig
    from .pushbullet import PushbulletNotificationConfig
    from .pushover import PushoverNotificationConfig
    from .telegram import TelegramNotificationConfig
    from .unitysvc_notify import UnitySVCNotificationConfig

    return {
        "email": EmailNotificationConfig,
        "pushbullet": PushbulletNotificationConfig,
        "pushover": PushoverNotificationConfig,
        "ntfy": NtfyNotificationConfig,
        "telegram": TelegramNotificationConfig,
        "unitysvc": UnitySVCNotificationConfig,
    }


def channel_config(
    cls: Type["NotificationConfig"], user_config: Any, section: Any = None
) -> "NotificationConfig":
    """A channel of type ``cls`` with the user's values, and the section's over them.

    Only the values a section sets replace the user's, not its defaults: a section with just
    a password keeps the user's ``max_retries``.
    """
    values: Dict[str, Any] = {f.name: getattr(user_config, f.name, None) for f in fields(cls)}
    if section is not None:
        set_keys = vars(section).get("set_keys")
        for key, value in vars(section).items():
            if (
                key in values
                and key not in ("type", "name", "request")
                and value is not None
                and (set_keys is None or key in set_keys)
            ):
                values[key] = value
    return cls(**values)


def section_channel_types(section: Any) -> List[str]:
    """The channel types a [notification.*] section sets up: the ones it has values for.

    Sections load as a class that accepts all of their keys, which can be a class of every
    channel type, so the type is told by the values instead.
    """
    from .notification import CHANNEL, RECIPIENT, fields_with_role

    return [
        channel_type
        for channel_type, cls in channel_classes().items()
        if any(
            getattr(section, f, None) is not None
            for f in fields_with_role(cls, CHANNEL) + fields_with_role(cls, RECIPIENT)
        )
    ]


def section_key(name: str, sections: Mapping[str, Any]) -> str:
    """The section a ``notify_with`` entry names, as "email.<name>" or "notification.<name>".

    An entry may leave out the kind when only one kind has a section of that name. Raises
    ValueError for an entry that names no section, or one of each kind.
    """
    if name in sections:
        return name
    matches = [key for key in sections if key.split(".", 1)[1] == name]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(
            f"{name} is both {' and '.join(matches)}: name one of them in notify_with."
        )
    raise ValueError(f"There is no email.{name} or notification.{name} section.")


def received_sections(user_config: Any, sections: Mapping[str, Any]) -> List[str]:
    """The enabled sections the user receives, in order, each once.

    ``sections`` are the [email.*] and [notification.*] sections, by "email.<name>" and
    "notification.<name>".
    """
    names = user_config.notify_with
    keys = list(sections) if names is None else [section_key(n, sections) for n in names]
    return list(dict.fromkeys(k for k in keys if sections[k].enabled is not False))


def user_channels(user_config: Any, sections: Mapping[str, Any]) -> List[Channel]:
    """The channels of a user, one per channel type of each section the user receives.

    A channel without its required fields is left out. A channel that is the same as an
    earlier one (it would send the same message) is sent once, through the earlier one.
    """
    classes = channel_classes()
    channels: List[Channel] = []
    for key in received_sections(user_config, sections):
        section = sections[key]
        types = section_channel_types(section)
        for channel_type in types:
            config = channel_config(classes[channel_type], user_config, section)
            label = key if len(types) == 1 else f"{key} ({channel_type})"
            channels.append(Channel(label, key, config))
    out: List[Channel] = []
    for channel in channels:
        if not channel.config._has_required_fields():
            continue
        same = next((i for i, c in enumerate(out) if c.config == channel.config), None)
        if same is None:
            out.append(channel)
        else:
            out[same] = replace(out[same], also=out[same].also + channel.sections)
    return out
