"""Daily digest: the searches, matches and rejected listings of the last 24 hours.

A user with ``digest_at = "08:00"`` receives, every day at that (local) time, a summary of
everything aimm did in the 24 hours up to that time, grouped by item with a total first. The
content is composed from the per-listing evaluation records (``evaluations.py``) and the
per-minute search counts of ``utils.counter``, and sent once a day in two versions chosen by
the channel type: a short phone version for push channels, and the full digest for email.

Delivery: each day's digest covers the 24 hours up to that day's ``digest_at`` (its cutoff),
whenever it is sent. Each channel remembers the cutoff of the last digest it received; a new
channel starts from the latest cutoff that has passed, so its first digest is the next one. A
channel that is behind (it failed, or aimm was not running) gets one digest from its last
cutoff (at most 7 days back) to the latest cutoff, never several stale digests in a row.

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
from datetime import datetime, timedelta
from logging import Logger
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Collection,
    Dict,
    Iterable,
    List,
    Mapping,
    Tuple,
    Type,
)

from diskcache import Cache  # type: ignore

from .evaluations import (
    EXCLUDED,
    NOTIFIED,
    PENDING,
    REJECTED,
    SOLD,
    EvaluationRecord,
    iter_evaluations,
)
from .utils import CacheType, CounterItem, cache, counter, hilight

if TYPE_CHECKING:
    from .digest_summary import Summarizer
    from .notification import NotificationConfig

DIGEST_PERIOD = 24 * 60 * 60
# earlier notified listings whose status changed in the window are listed as updates
UPDATE_LOOKBACK = 7 * DIGEST_PERIOD
# a catch-up digest goes back at most this far (the minute counters are kept 8 days)
MAX_CATCH_UP = 7 * DIGEST_PERIOD
# a window this much longer than a day (e.g. across a daylight saving change) is still a day
WINDOW_SLACK = 60 * 60
# entries listed per section of the email digest; the rest are summarized as "and N more"
MAX_ENTRIES = 20
# rejected listings per item in the email digest
MAX_REJECTED = 5
# matches listed by the phone digest
PHONE_ENTRIES = 3
# the phone digest fits the tightest push channel (Pushover takes 1024 characters)
PHONE_MAX_LENGTH = 1000
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
    # "sold", "pending" or ""
    state: str = ""


@dataclass
class ItemDigest:
    name: str
    searches: int = 0
    notified: List[DigestListing] = field(default_factory=list)
    rejected: List[DigestListing] = field(default_factory=list)
    updates: List[DigestListing] = field(default_factory=list)
    # number of excluded listings by reason
    excluded: Dict[str, int] = field(default_factory=dict)
    # a short AI-written summary of the item's day (see digest_summary.py), "" if none
    summary: str = ""

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
    # where the items left out of a phone digest are, e.g. " in the email digest"
    more_where: str = ""

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

    @property
    def is_daily(self: "Digest") -> bool:
        """Whether the digest covers a day, rather than catching up on several."""
        return self.until - self.since <= DIGEST_PERIOD + WINDOW_SLACK

    @property
    def window(self: "Digest") -> str:
        """``"in the last 24 hours"``, or ``"since Mon Oct 5 08:00"`` for a longer window."""
        if self.is_daily:
            return "in the last 24 hours"
        since = datetime.fromtimestamp(self.since)
        return f"since {since:%a %b} {since.day} {since:%H:%M}"


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


def _digest_listing(record: EvaluationRecord) -> DigestListing:
    price = _price(record.price)
    if record.previous_price and "|" not in record.price and record.price:
        price = f"{record.price} (was {record.previous_price})"
    return DigestListing(
        title=record.title,
        price=price,
        url=record.url.split("?")[0],
        location=record.location,
        item=record.item,
        time=record.time,
        rating=record.rating,
        comment=_shorten(record.ai_comment or record.reason or ""),
        state=record.state if record.state in (SOLD, PENDING) else "",
    )


def _is_update(record: EvaluationRecord, since: float, until: float) -> bool:
    """An earlier notified listing that sold, went pending or changed price in the window.

    The window's start is excluded: a change dated at a cutoff (by the status check before
    that digest) belongs to the digest ending there, not to the next one.
    """
    if record.stage != NOTIFIED or record.time >= since:
        return False
    if record.state in (SOLD, PENDING) and since < record.state_changed <= until:
        return True
    return bool(record.previous_price) and since < record.price_changed <= until


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
    ``"out of area"``). Earlier notified listings (up to UPDATE_LOOKBACK) whose state or price
    changed in the window are listed as updates.
    """
    latest: Dict[Tuple[str, str, str], EvaluationRecord] = {}
    updates: List[EvaluationRecord] = []
    for record in records:
        if _is_update(record, since, until):
            updates.append(record)
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
        listing = _digest_listing(record)
        if record.stage == NOTIFIED:
            digest.notified.append(listing)
        elif record.stage == REJECTED:
            digest.rejected.append(listing)

    for record in updates:
        item_digest(record.item).updates.append(_digest_listing(record))

    total = ItemDigest(name="Total")
    for digest in items.values():
        digest.notified.sort(key=_by_rating)
        digest.rejected.sort(key=_by_rating)
        digest.updates.sort(key=_by_rating)
        total.searches += digest.searches
        total.notified.extend(digest.notified)
        total.rejected.extend(digest.rejected)
        total.updates.extend(digest.updates)
        for reason, n in digest.excluded.items():
            total.excluded[reason] = total.excluded.get(reason, 0) + n
    total.notified.sort(key=_by_rating)
    total.rejected.sort(key=_by_rating)
    total.updates.sort(key=_by_rating)
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
    """The digest of all of aimm's activity from ``since`` to ``until``.

    By default, the 24 hours up to now.
    """
    until = time.time() if until is None else until
    since = until - DIGEST_PERIOD if since is None else since
    return build_digest(
        load_evaluations(since - UPDATE_LOOKBACK, local_cache=local_cache),
        counter.since(since, until, local_cache=local_cache),
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
        state = f" · {listing.state.capitalize()}" if listing.state else ""
        if self.fmt == "html":
            link = f'<a href="{html.escape(listing.url)}">{html.escape(title)}</a>'
            comment = f"<i>{self.text(comment)}</i>" if comment else ""
            tag = f" · <b>{listing.state.capitalize()}</b>" if listing.state else ""
            return f"• {rating}{link}{self.text(price)}{tag}{comment}"
        if self.fmt == "markdown":
            return f"- {rating}[{self.text(title)}]({listing.url}){self.text(price + state + comment)}"
        line = f"- {rating}{title}{price}{state}{comment}"
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
    when = "today" if digest.is_daily else digest.window
    return f"No matches {when}; aimm ran {_count(digest.total.searches, 'search')}."


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


def is_quiet(item: ItemDigest) -> bool:
    """An item with no evaluations and no updates in the window."""
    return not item.evaluated and not item.updates


def split_quiet(digest: Digest) -> Tuple[List[ItemDigest], List[ItemDigest]]:
    """The digest's items with something in the window, and the quiet ones, in their order."""
    active = [x for x in digest.items if not is_quiet(x)]
    return active, [x for x in digest.items if is_quiet(x)]


def _quiet_line(quiet: List[ItemDigest], digest: Digest) -> str:
    items = ", ".join(f"{x.name} ({_count(x.searches, 'search')})" for x in quiet)
    return f"Nothing new {digest.window}: {items}."


def _best_bet(item: ItemDigest) -> DigestListing | None:
    return next((x for x in item.notified if x.state != SOLD), None)


def _phone_summaries(digest: Digest, f: _Format, totals: str) -> str:
    lines = [totals]
    active, quiet = split_quiet(digest)
    # (lines, number of items they cover)
    blocks: List[Tuple[List[str], int]] = []
    for item in active:
        block = [f.bold(item.name) + f.text(": " + (item.summary or _counts(item)))]
        best = _best_bet(item)
        if best is not None:
            title = _shorten(best.title, PHONE_TITLE_LENGTH)
            if f.fmt == "html":
                block.append(f'<a href="{html.escape(best.url)}">{html.escape(title)}</a>')
            elif f.fmt == "markdown":
                block.append(f"[{f.text(title)}]({best.url})")
            else:
                block.append(best.url)
        blocks.append((block, 1))
    if quiet:
        blocks.append(([f.text(_quiet_line(quiet, digest))], len(quiet)))
    for n, (block, _) in enumerate(blocks):
        left = sum(size for _, size in blocks[n + 1 :])
        more = [f.text(f"…and {_count(left, 'more item')}{digest.more_where}")] if left else []
        if len(f.newline.join(lines + block + more)) > PHONE_MAX_LENGTH:
            rest = left + blocks[n][1]
            lines.append(f.text(f"…and {_count(rest, 'more item')}{digest.more_where}"))
            break
        lines.extend(block)
    return f.newline.join(lines)


def _phone_digest(digest: Digest, f: _Format) -> str:
    total = digest.total
    totals = (
        f"{'Last 24 h' if digest.is_daily else 'S' + digest.window[1:]}: "
        f"{_count(total.searches, 'search')}, "
        f"{total.evaluated:,} listings evaluated, {len(total.notified):,} notified, "
        f"{len(total.rejected):,} rejected by AI, {total.n_excluded:,} excluded"
    )
    if any(item.summary for item in digest.items):
        return _phone_summaries(digest, f, f.text(totals))
    lines = [f.text(totals)]
    if total.notified:
        lines.extend(
            _listings(f, "Top matches", total.notified, PHONE_ENTRIES, False, PHONE_TITLE_LENGTH)
        )
    else:
        lines.append(f.text(_no_matches(digest)))
    lines.extend(_listings(f, "Updates", total.updates, PHONE_ENTRIES, False, PHONE_TITLE_LENGTH))
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
            f"Listings evaluated {digest.window} ({digest.period})",
            f"Total: {_counts(digest.total)}",
        ]
    ]
    if not digest.total.notified:
        sections[0].append(_no_matches(digest))
    active, quiet = split_quiet(digest)
    for item in active:
        lines = [item.name, _counts(item)]
        if item.summary:
            lines.append(item.summary)
        lines.extend(_listings(f, "Notified", item.notified, MAX_ENTRIES, False))
        lines.extend(_listings(f, "Updates", item.updates, MAX_ENTRIES, False))
        lines.extend(_listings(f, "Rejected by AI", item.rejected, MAX_REJECTED, True))
        sections.append(lines)
    if quiet:
        sections.append([_quiet_line(quiet, digest)])
    return "\n\n".join("\n".join(lines) for lines in sections)


def render_email_digest(digest: Digest) -> Tuple[str, str]:
    """The full digest for email: plain text and HTML in the style of the listing emails."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=True)
    template = env.get_template("digest.html.j2")
    active, quiet = split_quiet(digest)
    html_message = template.render(
        digest=digest,
        items=active,
        quiet_line=_quiet_line(quiet, digest) if quiet else "",
        no_matches=_no_matches(digest),
        max_entries=MAX_ENTRIES,
        max_rejected=MAX_REJECTED,
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
    channels: Collection[str] | None = None,
) -> Dict[str, bool]:
    """Send the digest to the user's digest channels; whether each one succeeded.

    ``channels`` limits it to some of them (names as ``digest_channels`` returns them).
    """
    results: Dict[str, bool] = {}
    user_channels = digest_channels(user_config, notifications)
    email_class = channel_classes()["email"]
    digest.more_where = (
        " in the email digest"
        if any(isinstance(ch, email_class) for ch in user_channels.values())
        else ""
    )
    for name, channel in user_channels.items():
        if channels is not None and name not in channels:
            continue
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


def digest_key(user_name: str, channel: str) -> Tuple[str, str, str]:
    """Cache key of the cutoff of the last digest a channel received for a user."""
    return (CacheType.DIGEST.value, user_name, channel)


def latest_cutoff(digest_at: str, now: datetime) -> datetime:
    """The latest scheduled digest time (local) that has passed: today's, or yesterday's."""
    hour, minute = (int(x) for x in digest_at.split(":")[:2])
    cutoff = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if cutoff > now:
        cutoff -= timedelta(days=1)
    return cutoff


def pending_digest_windows(
    user_config: Any,
    notifications: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    local_cache: Cache | None = None,
) -> Dict[Tuple[float, float], List[str]]:
    """The windows due on the user's digest channels, as ``{(since, until): [channel, ...]}``.

    A channel is due when the latest scheduled cutoff has passed after the cutoff of the last
    digest it received. Its window ends at the latest cutoff and starts at its last cutoff, at
    most ``MAX_CATCH_UP`` back.

    A channel seen for the first time gets the latest cutoff that has passed as its starting
    point, without a digest, so that its first digest is the one at the next ``digest_at``
    (not one for a window that ended before the option was added).
    """
    c = cache if local_cache is None else local_cache
    now = datetime.now() if now is None else now
    until = latest_cutoff(user_config.digest_at, now).timestamp()
    windows: Dict[Tuple[float, float], List[str]] = {}
    for name in digest_channels(user_config, notifications):
        key = digest_key(user_config.name, name)
        last = c.get(key)
        if not isinstance(last, (int, float)):
            c.set(key, until, tag=CacheType.DIGEST.value)
            continue
        if last >= until:
            continue
        windows.setdefault((max(float(last), until - MAX_CATCH_UP), until), []).append(name)
    return windows


def pending_digest_channels(
    user_config: Any,
    notifications: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    local_cache: Cache | None = None,
) -> List[str]:
    """The user's digest channels that have not received the latest scheduled digest."""
    windows = pending_digest_windows(user_config, notifications, now, local_cache)
    return [name for names in windows.values() for name in names]


def send_due_digest(
    user_config: Any,
    notifications: Mapping[str, Any] | None = None,
    logger: Logger | None = None,
    now: datetime | None = None,
    local_cache: Cache | None = None,
    summarize: "Summarizer | None" = None,
    item_configs: Mapping[str, Any] | None = None,
) -> bool:
    """Send the user's digest to the channels it is due on; whether it was sent to any.

    The job runs at ``digest_at`` and whenever the jobs are scheduled (start, config change),
    so a restart does not send a digest twice, a digest missed while aimm was not running is
    sent on the next start, and a channel that failed is tried again with the same window.
    With ``summarize`` (given when an AI service is configured), each item gets an AI summary.
    """
    if not getattr(user_config, "digest_at", None) or user_config.enabled is False:
        return False
    c = cache if local_cache is None else local_cache
    windows = pending_digest_windows(user_config, notifications, now, local_cache)
    if not windows:
        if logger and not digest_channels(user_config, notifications):
            logger.warning(
                f"""{hilight("[Digest]", "fail")} No daily digest sent to {hilight(user_config.name)}: the user has no notification channel for the digest."""
            )
        return False

    sent_with: List[str] = []
    failed: List[str] = []
    for (since, until), names in windows.items():
        digest = compose_digest(since, until, local_cache=local_cache)
        if summarize is not None:
            from .digest_summary import add_summaries

            add_summaries(digest, summarize, item_configs, logger=logger, local_cache=local_cache)
        results = send_digest(user_config, digest, notifications, logger=logger, channels=names)
        for name, sent in results.items():
            if sent:
                # the window this channel has received, so that it is not sent again
                c.set(digest_key(user_config.name, name), until, tag=CacheType.DIGEST.value)
                sent_with.append(name)
            else:
                failed.append(name)
    if logger and sent_with:
        logger.info(
            f"""{hilight("[Digest]", "succ")} Sent the daily digest to {hilight(user_config.name)} with {", ".join(sent_with)}."""
        )
    if logger and failed:
        logger.warning(
            f"""{hilight("[Digest]", "fail")} Failed to send the daily digest to {hilight(user_config.name)} with {", ".join(failed)}; it is tried again when aimm restarts or reloads its config."""
        )
    return bool(sent_with)
