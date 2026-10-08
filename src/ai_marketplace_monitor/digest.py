"""Daily digest: the searches, matches and rejected listings of the last 24 hours.

A user with ``digest_at = "08:00"`` receives, every day at that (local) time, a summary of
everything aimm did in the last 24 hours, grouped by item with a total first. The content is
composed from the per-listing evaluation records (``evaluations.py``) and the per-hour counters of
``utils.counter``, and sent once a day in two versions chosen by the channel type: a short
phone version for push channels, and the full digest for email.

Entry points:

- ``compose_digest(since, until)`` collects the records and counters into a ``Digest``;
- ``render_phone_digest(digest, fmt)`` and ``render_email_digest(digest)`` render it without
  sending;
- ``send_digest(user_config, digest, notifications)`` sends it to the user's digest channels;
- ``send_due_digest(user_config, notifications)`` does all of this when the digest is due.
"""

import html
import re
import time
from dataclasses import dataclass, field, fields
from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Tuple,
    Type,
)

from diskcache import Cache  # type: ignore

from .evaluations import EXCLUDED, NOTIFIED, REJECTED, EvaluationRecord, iter_evaluations
from .utils import CacheType, CounterItem, cache, counter, hilight

if TYPE_CHECKING:
    from .notification import NotificationConfig

DIGEST_PERIOD = 24 * 60 * 60
# entries listed per section of the email digest; the rest are summarized as "and N more"
MAX_ENTRIES = 20
# matches listed by the phone digest
PHONE_ENTRIES = 3
# the phone digest fits the tightest push channel (Pushover takes 1024 characters, and
# UnitySVC can forward to SMS-like destinations)
PHONE_MAX_LENGTH = 700
PHONE_TITLE_LENGTH = 60
MAX_COMMENT_LENGTH = 80


@dataclass
class DigestListing:
    title: str
    price: str
    url: str
    location: str
    item: str
    time: float
    rating: int | None = None
    comment: str = ""


@dataclass
class ItemDigest:
    name: str
    searches: int = 0
    notified: List[DigestListing] = field(default_factory=list)
    rejected: List[DigestListing] = field(default_factory=list)
    # number of excluded listings by reason
    excluded: Dict[str, int] = field(default_factory=dict)

    @property
    def n_excluded(self: "ItemDigest") -> int:
        return sum(self.excluded.values())

    @property
    def evaluated(self: "ItemDigest") -> int:
        """Distinct listings decided on: notified, rejected by AI or excluded."""
        return len(self.notified) + len(self.rejected) + self.n_excluded


@dataclass
class Digest:
    since: float
    until: float
    total: ItemDigest
    items: List[ItemDigest] = field(default_factory=list)

    @property
    def title(self: "Digest") -> str:
        n = len(self.total.notified)
        if n == 0:
            return f"AI Marketplace Monitor daily digest: no matches in {_count(self.total.searches, 'search')}"
        return f"AI Marketplace Monitor daily digest: {_count(n, 'match')}"

    @property
    def period(self: "Digest") -> str:
        def fmt(t: float) -> str:
            return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")

        return f"{fmt(self.since)} to {fmt(self.until)}"


def _count(n: int, noun: str) -> str:
    plural = noun + ("es" if noun.endswith(("s", "ch", "sh")) else "s")
    return f"{n:,} {noun if n == 1 else plural}"


def _shorten(text: str, length: int = MAX_COMMENT_LENGTH) -> str:
    text = " ".join(text.split())
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def _price(price: str) -> str:
    """``"$180 | $250"`` (a price drop) as ``"$180 (was $250)"``."""
    if "|" not in price:
        return price
    new, old = (x.strip() for x in price.split("|", 1))
    return f"{new} (was {old})"


def _by_rating(listing: DigestListing) -> Tuple[int, float]:
    """Best ratings first, then the most recent."""
    return (-(listing.rating if listing.rating is not None else -1), -listing.time)


def build_digest(
    records: Iterable[EvaluationRecord],
    counters: Mapping[str, Mapping[str, int]],
    since: float,
    until: float,
) -> Digest:
    """Compose a digest from evaluation records and ``counter.since()`` counts.

    A listing counts once per item, with its latest decision. The records keep only the last
    decision of a listing, so a listing still on the market is evaluated, and listed, again in
    the next digest: the digest reports listings evaluated in the period, not new listings.
    Exclusions are grouped by the kind of reason (``"out of area: Austin, TX"`` counts as
    ``"out of area"``).
    """
    latest: Dict[Tuple[str, str, str], EvaluationRecord] = {}
    for record in records:
        if not since <= record.time <= until:
            continue
        key = (record.item, record.marketplace, record.id)
        if key not in latest or latest[key].time <= record.time:
            latest[key] = record

    items: Dict[str, ItemDigest] = {}

    def item_digest(name: str) -> ItemDigest:
        if name not in items:
            items[name] = ItemDigest(name=name)
        return items[name]

    for name, counts in counters.items():
        searches = counts.get(CounterItem.SEARCH_PERFORMED.value, 0)
        if searches:
            item_digest(name).searches = searches

    for record in latest.values():
        digest = item_digest(record.item)
        if record.stage == EXCLUDED:
            reason = record.reason.split(":")[0].strip() or "other"
            digest.excluded[reason] = digest.excluded.get(reason, 0) + 1
            continue
        listing = DigestListing(
            title=record.title,
            price=_price(record.price),
            url=record.url.split("?")[0],
            location=record.location,
            item=record.item,
            time=record.time,
            rating=record.rating,
            comment=_shorten(record.ai_comment or record.reason or ""),
        )
        if record.stage == NOTIFIED:
            digest.notified.append(listing)
        elif record.stage == REJECTED:
            digest.rejected.append(listing)

    total = ItemDigest(name="Total")
    for digest in items.values():
        digest.notified.sort(key=_by_rating)
        digest.rejected.sort(key=_by_rating)
        total.searches += digest.searches
        total.notified.extend(digest.notified)
        total.rejected.extend(digest.rejected)
        for reason, n in digest.excluded.items():
            total.excluded[reason] = total.excluded.get(reason, 0) + n
    total.notified.sort(key=_by_rating)
    total.rejected.sort(key=_by_rating)
    return Digest(
        since=since,
        until=until,
        total=total,
        items=sorted(items.values(), key=lambda x: x.name.lower()),
    )


def load_evaluations(since: float, local_cache: Cache | None = None) -> List[EvaluationRecord]:
    """The evaluation records since a time (none if the cache cannot be read)."""
    return list(iter_evaluations(since=since, local_cache=local_cache))


def compose_digest(
    since: float | None = None,
    until: float | None = None,
    local_cache: Cache | None = None,
) -> Digest:
    """The digest of all of aimm's activity, by default in the last 24 hours."""
    until = time.time() if until is None else until
    since = until - DIGEST_PERIOD if since is None else since
    return build_digest(
        load_evaluations(since, local_cache=local_cache),
        counter.since(since, local_cache=local_cache),
        since,
        until,
    )


#
# Rendering
#
class _Format:
    """Plain text, Markdown or HTML (as push channels accept it) building blocks."""

    def __init__(self: "_Format", fmt: str) -> None:
        self.fmt = fmt if fmt in ("plain_text", "markdown", "html") else "plain_text"
        self.newline = "<br>" if self.fmt == "html" else "\n"

    def text(self: "_Format", text: str) -> str:
        if self.fmt == "html":
            return html.escape(text)
        if self.fmt == "markdown":
            return re.sub(r"([\\`*_\[\]])", r"\\\1", text)
        return text

    def bold(self: "_Format", text: str) -> str:
        if self.fmt == "html":
            return f"<b>{self.text(text)}</b>"
        if self.fmt == "markdown":
            return f"**{self.text(text)}**"
        return text

    def listing(
        self: "_Format", listing: DigestListing, with_comment: bool, title_length: int = 0
    ) -> str:
        rating = f"[{listing.rating}] " if listing.rating is not None else ""
        title = _shorten(listing.title, title_length) if title_length else listing.title
        price = f", {listing.price}" if listing.price else ""
        comment = f": {listing.comment}" if with_comment and listing.comment else ""
        if self.fmt == "html":
            link = f'<a href="{html.escape(listing.url)}">{html.escape(title)}</a>'
            comment = f"<i>{self.text(comment)}</i>" if comment else ""
            return f"• {rating}{link}{self.text(price)}{comment}"
        if self.fmt == "markdown":
            return f"- {rating}[{self.text(title)}]({listing.url}){self.text(price + comment)}"
        line = f"- {rating}{title}{price}{comment}"
        return line if with_comment else f"{line}\n  {listing.url}"


def _counts(digest: ItemDigest) -> str:
    parts = [
        _count(digest.searches, "search"),
        f"{digest.evaluated:,} listings evaluated",
        f"{len(digest.notified):,} notified",
        f"{len(digest.rejected):,} rejected by AI",
    ]
    excluded = f"{digest.n_excluded:,} excluded"
    if digest.excluded:
        reasons = sorted(digest.excluded.items(), key=lambda x: -x[1])
        excluded += " (" + ", ".join(f"{reason} {n:,}" for reason, n in reasons) + ")"
    return ", ".join([*parts, excluded])


def _no_matches(digest: Digest) -> str:
    return f"No matches today; aimm ran {_count(digest.total.searches, 'search')}."


def _listings(
    f: _Format,
    title: str,
    listings: List[DigestListing],
    limit: int,
    with_comment: bool,
    title_length: int = 0,
) -> List[str]:
    if not listings:
        return []
    lines = [f.bold(f"{title} ({len(listings):,})")]
    lines.extend(f.listing(x, with_comment, title_length) for x in listings[:limit])
    if len(listings) > limit:
        lines.append(f.text(f"…and {len(listings) - limit:,} more"))
    return lines


def _phone_digest(digest: Digest, f: _Format) -> str:
    total = digest.total
    totals = (
        f"Last 24 h: {_count(total.searches, 'search')}, "
        f"{total.evaluated:,} listings evaluated, {len(total.notified):,} notified, "
        f"{len(total.rejected):,} rejected by AI, {total.n_excluded:,} excluded"
    )
    lines = [f.text(totals)]
    if total.notified:
        lines.extend(
            _listings(f, "Top matches", total.notified, PHONE_ENTRIES, False, PHONE_TITLE_LENGTH)
        )
    else:
        lines.append(f.text(_no_matches(digest)))
    return f.newline.join(lines)


def render_phone_digest(digest: Digest, fmt: str = "plain_text") -> str:
    """The short digest for push channels, in their ``message_format``.

    One line of totals, then the top matches (or why there are none), short enough for the
    tightest push channel.
    """
    message = _phone_digest(digest, _Format(fmt))
    if len(message) <= PHONE_MAX_LENGTH:
        return message
    # very long prices or links: cutting HTML or Markdown can leave a tag or a link open
    message = _phone_digest(digest, _Format("plain_text"))
    return message if len(message) <= PHONE_MAX_LENGTH else message[: PHONE_MAX_LENGTH - 1] + "…"


def _email_text(digest: Digest) -> str:
    f = _Format("plain_text")
    sections = [
        [
            f"Listings evaluated in the last 24 hours ({digest.period})",
            f"Total: {_counts(digest.total)}",
        ]
    ]
    if not digest.total.notified:
        sections[0].append(_no_matches(digest))
    for item in digest.items:
        lines = [item.name, _counts(item)]
        lines.extend(_listings(f, "Notified", item.notified, MAX_ENTRIES, False))
        lines.extend(_listings(f, "Rejected by AI", item.rejected, MAX_ENTRIES, True))
        sections.append(lines)
    return "\n\n".join("\n".join(lines) for lines in sections)


def render_email_digest(digest: Digest) -> Tuple[str, str]:
    """The full digest for email: plain text and HTML in the style of the listing emails."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=True)
    template = env.get_template("digest.html.j2")
    html_message = template.render(
        digest=digest, no_matches=_no_matches(digest), max_entries=MAX_ENTRIES
    )
    return _email_text(digest), html_message


#
# Sending
#
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


def _channel(
    cls: Type["NotificationConfig"], user_config: Any, section: Any = None
) -> "NotificationConfig":
    """A channel with the user's values, and a section's, like Config.expand_notifications."""
    values = {f.name: getattr(user_config, f.name) for f in fields(cls)}
    if section is not None:
        for key, value in vars(section).items():
            if key in values and key not in ("type", "name", "request") and value is not None:
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


def digest_channels(
    user_config: Any, notifications: Mapping[str, Any] | None = None
) -> Dict[str, "NotificationConfig"]:
    """The channels that receive the user's digest.

    With ``digest_with``, the named [notification.*] sections (from ``Config.notification``),
    by section name; otherwise every channel the user is notified with, by channel type.
    """
    classes = channel_classes()
    channels: Dict[str, NotificationConfig] = {}
    if getattr(user_config, "digest_with", None) is None:
        for channel_type, cls in classes.items():
            channel = _channel(cls, user_config)
            if channel._has_required_fields():
                channels[channel_type] = channel
        return channels

    if notifications is None:
        raise ValueError("digest_with needs the [notification.*] sections.")
    for name in user_config.digest_with:
        section = notifications.get(name)
        if section is None or section.enabled is False:
            continue
        types = section_channel_types(section)
        for channel_type in types:
            channel = _channel(classes[channel_type], user_config, section)
            if channel._has_required_fields():
                channels[name if len(types) == 1 else f"{name} ({channel_type})"] = channel
    return channels


def send_digest(
    user_config: Any,
    digest: Digest,
    notifications: Mapping[str, Any] | None = None,
    logger: Logger | None = None,
) -> Dict[str, bool]:
    """Send the digest to the user's digest channels; whether each one succeeded."""
    results: Dict[str, bool] = {}
    for name, channel in digest_channels(user_config, notifications).items():
        try:
            results[name] = channel.send_digest(digest, logger=logger)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if logger:
                logger.error(
                    f"""{hilight("[Digest]", "fail")} Failed to send the digest to {user_config.name} with {name}: {e}"""
                )
            results[name] = False
    return results


def digest_key(user_name: str) -> Tuple[str, str]:
    return (CacheType.DIGEST.value, user_name)


def is_digest_due(digest_at: str, last_sent: str | None, now: datetime) -> bool:
    """Whether today's digest time has passed and today's digest has not been sent.

    This also sends a digest missed while aimm was not running, once, on the next start.
    """
    hour, minute = (int(x) for x in digest_at.split(":")[:2])
    return now >= now.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    ) and last_sent != now.strftime("%Y-%m-%d")


def send_due_digest(
    user_config: Any,
    notifications: Mapping[str, Any] | None = None,
    logger: Logger | None = None,
    now: datetime | None = None,
    local_cache: Cache | None = None,
) -> bool:
    """Send the user's digest if it is due; whether one was sent."""
    if not getattr(user_config, "digest_at", None) or user_config.enabled is False:
        return False
    c = cache if local_cache is None else local_cache
    now = datetime.now() if now is None else now
    key = digest_key(user_config.name)
    if not is_digest_due(user_config.digest_at, c.get(key), now):
        return False

    digest = compose_digest(until=now.timestamp(), local_cache=local_cache)
    results = send_digest(user_config, digest, notifications, logger=logger)
    if not any(results.values()):
        if logger:
            logger.warning(
                f"""{hilight("[Digest]", "fail")} No daily digest sent to {hilight(user_config.name)}: """
                + (
                    "all channels failed."
                    if results
                    else "the user has no notification channel for the digest."
                )
            )
        return False
    # remember the day, so that a restart or a config change does not send it again
    c.set(key, now.strftime("%Y-%m-%d"), tag=CacheType.DIGEST.value)
    if logger:
        logger.info(
            f"""{hilight("[Digest]", "succ")} Sent the daily digest to {hilight(user_config.name)} with {", ".join(k for k, v in results.items() if v)}."""
        )
    return True
