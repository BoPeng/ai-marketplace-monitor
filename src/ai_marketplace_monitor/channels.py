"""The channels a user is notified through: one for each section the user receives.

A user receives the [notification.*] sections named in ``notify_with`` (every enabled one
when it is unset). Each section sends on its own, with the user's values (such as the
recipient) under the section's: a user can receive two email sections, or two Telegram bots.
Values set in [user.*] alone make a channel of a type that no section the user receives sets
up. Alerts, the digest and test messages all go through these channels.
"""

from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Tuple, Type

if TYPE_CHECKING:
    from .notification import NotificationConfig


@dataclass(frozen=True)
class Channel:
    """One way a user is notified."""

    # the section's name; "<section> (<type>)" for a section of several channel types; the
    # channel type for a channel set up in [user.*]
    name: str
    # the [notification.*] section; None for a channel set up in [user.*]
    section: str | None
    config: "NotificationConfig"
    # other sections the user receives that send the same message, sent once through this one
    also: Tuple[str, ...] = ()

    @property
    def sections(self: "Channel") -> Tuple[str, ...]:
        """The sections this channel sends for: none for a channel set up in [user.*]."""
        return ((self.section,) if self.section is not None else ()) + self.also

    def in_digest(self: "Channel", digest_with: List[str] | None) -> bool:
        """Whether the channel receives the digest: all do, or ``digest_with`` names it."""
        return digest_with is None or any(s in digest_with for s in self.sections)

    @property
    def label(self: "Channel") -> str:
        """How the channel is shown: its name, and its type if the name does not say it."""
        channel_type = self.config.notify_method
        return self.name if channel_type in self.name else f"{self.name} ({channel_type})"


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


def received_sections(user_config: Any, notifications: Mapping[str, Any]) -> List[str]:
    """The enabled [notification.*] sections the user receives, in order."""
    names = user_config.notify_with
    return [
        name
        for name in (notifications if names is None else names)
        if name in notifications and notifications[name].enabled is not False
    ]


def user_channels(user_config: Any, notifications: Mapping[str, Any]) -> List[Channel]:
    """The channels of a user.

    One per channel type of each section received, then the channels set up in [user.*]
    alone. A channel without its required fields is left out. A channel that is the same as an
    earlier one (it would send the same message) is sent once, through the earlier one, which
    keeps both sections (for ``digest_with``).
    """
    classes = channel_classes()
    channels: List[Channel] = []
    covered = set()
    for name in received_sections(user_config, notifications):
        section = notifications[name]
        types = section_channel_types(section)
        for channel_type in types:
            covered.add(channel_type)
            config = channel_config(classes[channel_type], user_config, section)
            label = name if len(types) == 1 else f"{name} ({channel_type})"
            channels.append(Channel(label, name, config))
    for channel_type, cls in classes.items():
        if channel_type not in covered:
            config = channel_config(cls, user_config)
            label = channel_type if channel_type not in notifications else f"{channel_type} (user)"
            channels.append(Channel(label, None, config))
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
