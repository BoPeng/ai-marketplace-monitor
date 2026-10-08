"""Daily digest: the searches, matches and rejected listings of the last 24 hours.

A user with ``digest = "08:00"`` receives, every day at that (local) time, a summary of
everything aimm did in the last 24 hours, grouped by item with a total first. The content is
composed from the per-listing evaluation records (#401) and the per-hour counters of
``utils.counter``, rendered for each channel's format, and sent once a day.

Entry points:

- ``compose_digest(since, until)`` collects the records and counters into a ``Digest``;
- ``render_digest(digest, fmt)`` / ``render_digest_email(digest)`` render it without sending;
- ``send_digest(user_config, digest)`` sends it to the user's digest channels;
- ``send_due_digest(user_config)`` does all of this when the user's digest is due.
"""

import html
import importlib
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
    Protocol,
    Tuple,
    Type,
)

from diskcache import Cache  # type: ignore

from .utils import CacheType, CounterItem, cache, counter, hilight

if TYPE_CHECKING:
    from .notification import NotificationConfig

DIGEST_PERIOD = 24 * 60 * 60
# entries listed per section; the rest are summarized as "and N more"
MAX_ENTRIES = 20
# matches listed by the short digest sent to channels with a length limit
SHORT_ENTRIES = 3
MAX_COMMENT_LENGTH = 80
# channel types a digest can be sent to, as in [notification.*] `type`
DIGEST_CHANNEL_TYPES = ("email", "pushbullet", "pushover", "ntfy", "telegram", "unitysvc")
# channels that receive the digest when `digest_channels` is not set; if the user has none
# of them, the digest goes to all of the user's channels
EMAIL_LIKE_CHANNELS = ("email", "unitysvc")


class EvaluationLike(Protocol):
    """The fields of a #401 ``EvaluationRecord`` that the digest uses."""

    time: float
    item: str
    marketplace: str
    id: str
    url: str
    title: str
    price: str
    location: str
    stage: str  # "excluded" | "rejected" | "notified"
    rating: int | None
    ai_comment: str
    reason: str


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
    examined: int = 0
    rated: int = 0
    notified: List[DigestListing] = field(default_factory=list)
    rejected: List[DigestListing] = field(default_factory=list)
    # number of excluded listings by reason
    excluded: Dict[str, int] = field(default_factory=dict)

    @property
    def n_excluded(self: "ItemDigest") -> int:
        return sum(self.excluded.values())


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


def _by_rating(listing: DigestListing) -> Tuple[int, float]:
    """Best ratings first, then the most recent."""
    return (-(listing.rating if listing.rating is not None else -1), -listing.time)


def build_digest(
    records: Iterable[EvaluationLike],
    counters: Mapping[str, Mapping[str, int]],
    since: float,
    until: float,
) -> Digest:
    """Compose a digest from evaluation records and ``counter.since()`` counts.

    A listing evaluated more than once in the period counts once, with its latest decision.
    """
    latest: Dict[Tuple[str, str, str], EvaluationLike] = {}
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
        examined = counts.get(CounterItem.LISTING_EXAMINED.value, 0)
        if searches or examined:
            digest = item_digest(name)
            digest.searches, digest.examined = searches, examined

    for record in latest.values():
        digest = item_digest(record.item)
        if record.rating is not None:
            digest.rated += 1
        if record.stage == "excluded":
            reason = record.reason or "other"
            digest.excluded[reason] = digest.excluded.get(reason, 0) + 1
            continue
        listing = DigestListing(
            title=record.title,
            price=record.price,
            url=record.url.split("?")[0],
            location=record.location,
            item=record.item,
            time=record.time,
            rating=record.rating,
            comment=_shorten(record.ai_comment or record.reason or ""),
        )
        if record.stage == "notified":
            digest.notified.append(listing)
        elif record.stage == "rejected":
            digest.rejected.append(listing)

    total = ItemDigest(name="Total")
    for digest in items.values():
        # a listing is examined at least once; counters can miss it (e.g. after a cache reset)
        digest.examined = max(
            digest.examined, len(digest.notified) + len(digest.rejected) + digest.n_excluded
        )
        digest.notified.sort(key=_by_rating)
        digest.rejected.sort(key=_by_rating)
        total.searches += digest.searches
        total.examined += digest.examined
        total.rated += digest.rated
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


def load_evaluations(since: float, local_cache: Cache | None = None) -> List[EvaluationLike]:
    """The evaluation records since a time, or none if they are not available."""
    # TODO(#401): import iter_evaluations from .evaluations directly once #401 has merged.
    try:
        evaluations: Any = importlib.import_module(f"{__package__}.evaluations")
    except ImportError:
        return []
    return list(evaluations.iter_evaluations(since=since, local_cache=local_cache))


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

    def listing(self: "_Format", listing: DigestListing, with_comment: bool) -> str:
        rating = f"[{listing.rating}] " if listing.rating is not None else ""
        price = f", {listing.price}" if listing.price else ""
        comment = f": {listing.comment}" if with_comment and listing.comment else ""
        if self.fmt == "html":
            title = f'<a href="{html.escape(listing.url)}">{html.escape(listing.title)}</a>'
            comment = f"<i>{self.text(comment)}</i>" if comment else ""
            return f"• {rating}{title}{self.text(price)}{comment}"
        if self.fmt == "markdown":
            title = f"[{self.text(listing.title)}]({listing.url})"
            return f"- {rating}{title}{self.text(price + comment)}"
        line = f"- {rating}{listing.title}{price}{comment}"
        return line if with_comment else f"{line}\n  {listing.url}"


def _counts(digest: ItemDigest) -> str:
    parts = [
        _count(digest.searches, "search"),
        f"{digest.examined:,} examined",
        f"{digest.rated:,} rated by AI",
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
    f: _Format, title: str, listings: List[DigestListing], limit: int, with_comment: bool
) -> List[str]:
    if not listings:
        return []
    lines = [f.bold(f"{title} ({len(listings):,})")]
    lines.extend(f.listing(x, with_comment) for x in listings[:limit])
    if len(listings) > limit:
        lines.append(f.text(f"…and {len(listings) - limit:,} more"))
    return lines


def _full_digest(digest: Digest, f: _Format) -> str:
    sections = [
        [
            f.text(f"Last 24 hours ({digest.period})"),
            f.bold("Total:") + " " + f.text(_counts(digest.total)),
        ]
    ]
    if not digest.total.notified:
        sections[0].append(f.text(_no_matches(digest)))
    for item in digest.items:
        lines = [f.bold(item.name), f.text(_counts(item))]
        lines.extend(_listings(f, "Notified", item.notified, MAX_ENTRIES, False))
        lines.extend(_listings(f, "Rejected by AI", item.rejected, MAX_ENTRIES, True))
        sections.append(lines)
    return (f.newline * 2).join(f.newline.join(lines) for lines in sections)


def _short_digest(digest: Digest, f: _Format) -> str:
    lines = [f.bold("Total:") + " " + f.text(_counts(digest.total))]
    if digest.total.notified:
        lines.extend(_listings(f, "Notified", digest.total.notified, SHORT_ENTRIES, False))
    else:
        lines.append(f.text(_no_matches(digest)))
    return f.newline.join(lines)


def render_digest(digest: Digest, fmt: str = "plain_text", max_length: int | None = None) -> str:
    """Render the digest as plain text, Markdown or HTML (``message_format``).

    A channel with a length limit gets the counts and the top matches if the full digest is
    too long, cut to the limit if even that is too long.
    """
    f = _Format(fmt)
    message = _full_digest(digest, f)
    if max_length is None or len(message) <= max_length:
        return message
    message = _short_digest(digest, f)
    if len(message) <= max_length:
        return message
    # cutting HTML or Markdown can leave a tag or a link open, so fall back to plain text
    message = _short_digest(digest, _Format("plain_text"))
    return message if len(message) <= max_length else message[: max_length - 1] + "…"


def render_digest_email(digest: Digest) -> str:
    """The HTML email of the digest, in the style of the listing emails."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=True)
    template = env.get_template("digest.html.j2")
    return template.render(
        digest=digest,
        no_matches=_no_matches(digest),
        max_entries=MAX_ENTRIES,
    )


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


def digest_channels(user_config: Any) -> Dict[str, "NotificationConfig"]:
    """The user's channels that receive the digest, by channel type."""
    available: Dict[str, NotificationConfig] = {}
    for channel_type, cls in channel_classes().items():
        channel = cls(**{f.name: getattr(user_config, f.name) for f in fields(cls)})
        if channel._has_required_fields():
            available[channel_type] = channel
    selected = getattr(user_config, "digest_channels", None)
    if selected is not None:
        return {k: v for k, v in available.items() if k in selected}
    return {k: v for k, v in available.items() if k in EMAIL_LIKE_CHANNELS} or available


def send_digest(user_config: Any, digest: Digest, logger: Logger | None = None) -> Dict[str, bool]:
    """Send the digest to the user's digest channels; whether each one succeeded."""
    results: Dict[str, bool] = {}
    for channel_type, channel in digest_channels(user_config).items():
        try:
            results[channel_type] = channel.send_digest(digest, logger=logger)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if logger:
                logger.error(
                    f"""{hilight("[Digest]", "fail")} Failed to send the digest to {user_config.name} by {channel_type}: {e}"""
                )
            results[channel_type] = False
    return results


def digest_key(user_name: str) -> Tuple[str, str]:
    return (CacheType.DIGEST.value, user_name)


def is_digest_due(digest_time: str, last_sent: str | None, now: datetime) -> bool:
    """Whether today's digest time has passed and today's digest has not been sent.

    This also sends a digest missed while aimm was not running, once, on the next start.
    """
    hour, minute = (int(x) for x in digest_time.split(":")[:2])
    return now >= now.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    ) and last_sent != now.strftime("%Y-%m-%d")


def send_due_digest(
    user_config: Any,
    logger: Logger | None = None,
    now: datetime | None = None,
    local_cache: Cache | None = None,
) -> bool:
    """Send the user's digest if it is due; whether one was sent."""
    if not getattr(user_config, "digest", None) or user_config.enabled is False:
        return False
    c = cache if local_cache is None else local_cache
    now = datetime.now() if now is None else now
    key = digest_key(user_config.name)
    if not is_digest_due(user_config.digest, c.get(key), now):
        return False

    digest = compose_digest(until=now.timestamp(), local_cache=local_cache)
    results = send_digest(user_config, digest, logger=logger)
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
            f"""{hilight("[Digest]", "succ")} Sent the daily digest to {hilight(user_config.name)} by {", ".join(k for k, v in results.items() if v)}."""
        )
    return True
