"""A record of every listing aimm evaluated, and what it decided.

Each decision (excluded before the AI, rejected by the AI rating, or notified) is written to the
cache under ``(evaluations, marketplace, listing_id, item_name)``. A later decision about the same
listing and item overwrites the earlier one, so the history holds one row per listing and item.
Records expire after ``[monitor] evaluation_history_days`` (30 days by default).
Each record also keeps the listing's status (last seen in search results, price changes, sold or
pending), which later searches and the digest's status check update without changing the decision.
"""

from __future__ import annotations

import logging
import time
from dataclasses import MISSING, asdict, dataclass, fields
from typing import Any, Dict, Iterable, Iterator, List

from diskcache import Cache  # type: ignore

from .listing import Listing
from .utils import CacheType, cache, is_cache_broken

logger = logging.getLogger(__name__)

EXCLUDED = "excluded"  # dropped before the AI: keywords, area or seller
REJECTED = "rejected"  # AI rating below the item's threshold
NOTIFIED = "notified"  # a notification was sent
STAGES = (EXCLUDED, REJECTED, NOTIFIED)

# what a listing's page said when aimm last checked it (see refresh in monitor.py)
AVAILABLE = "available"
PENDING = "pending"
SOLD = "sold"
UNKNOWN = "unknown"

DEFAULT_HISTORY_DAYS = 30
_history_days: float = DEFAULT_HISTORY_DAYS


def set_history_days(days: float | None) -> None:
    """Keep new records this many days (``None`` restores the default)."""
    global _history_days
    _history_days = DEFAULT_HISTORY_DAYS if days is None else days


@dataclass
class EvaluationRecord:
    time: float  # epoch seconds of the decision
    item: str  # item name
    marketplace: str
    id: str  # listing id
    url: str
    title: str
    price: str
    location: str
    seller: str
    condition: str
    stage: str  # "excluded" | "rejected" | "notified"
    rating: int | None  # AI score 1-5, None if not rated
    ai_comment: str  # "" if not rated
    reason: str  # short human-readable reason ("" for notified)
    # the listing's status, updated without changing the decision above
    last_seen: float = 0.0  # last time the listing was in search results
    previous_price: str = ""  # the price before the latest change, "" if none
    price_changed: float = 0.0  # when the price last changed
    state: str = UNKNOWN  # AVAILABLE, PENDING, SOLD or UNKNOWN
    state_changed: float = 0.0  # when the state last changed
    checked: float = 0.0  # last time the listing page was opened for its status

    @classmethod
    def from_listing(
        cls: type["EvaluationRecord"],
        listing: Listing,
        *,
        item: str,
        stage: str,
        rating: int | None = None,
        ai_comment: str = "",
        reason: str = "",
    ) -> "EvaluationRecord":
        return cls(
            time=time.time(),
            item=item,
            marketplace=listing.marketplace,
            id=listing.id,
            url=listing.post_url.split("?")[0],
            title=listing.title,
            price=listing.price,
            location=listing.location,
            seller=listing.seller,
            condition=listing.condition,
            stage=stage,
            rating=rating,
            ai_comment=ai_comment,
            reason=reason,
        )

    @classmethod
    def from_dict(cls: type["EvaluationRecord"], value: Dict[str, Any]) -> "EvaluationRecord":
        """Build a record from a cached dict, tolerating missing or extra keys."""
        names = {f.name: f for f in fields(cls)}
        values: Dict[str, Any] = dict.fromkeys(names, "")
        for name, f in names.items():
            if f.default is not MISSING:
                values[name] = f.default
        values.update({k: v for k, v in value.items() if k in names})
        values["time"] = float(values["time"] or 0)
        for name in ("last_seen", "price_changed", "state_changed", "checked"):
            values[name] = float(values[name] or 0)
        rating = values["rating"]
        values["rating"] = int(rating) if isinstance(rating, (int, float)) else None
        return cls(**values)

    def to_dict(self: "EvaluationRecord") -> Dict[str, Any]:
        return asdict(self)


def _first_price(price: str) -> str:
    """``"$80 | $100"`` (a reduced price, as search results show it) as ``"$80"``."""
    return price.split("|", 1)[0].strip()


def apply_price(record: EvaluationRecord, price: str, now: float) -> None:
    """Record a listing's current price, remembering the previous one when it changed."""
    if not price:
        return
    current = _first_price(price)
    before = _first_price(record.price)
    if before and current != before:
        record.previous_price = before
        record.price_changed = now
    elif "|" in price and not record.previous_price:
        # the card shows the old price too: a drop aimm did not see happen
        record.previous_price = price.split("|", 1)[1].strip()
        record.price_changed = now
    record.price = price


def _key(marketplace: str, listing_id: str, item: str) -> tuple:
    return (CacheType.EVALUATIONS.value, marketplace, listing_id, item)


def _save(c: Cache, record: EvaluationRecord) -> None:
    c.set(
        _key(record.marketplace, record.id, record.item),
        record.to_dict(),
        expire=_history_days * 24 * 60 * 60,
        tag=CacheType.EVALUATIONS.value,
    )


def _load(c: Cache, marketplace: str, listing_id: str, item: str) -> EvaluationRecord | None:
    value = c.get(_key(marketplace, listing_id, item))
    return EvaluationRecord.from_dict(value) if isinstance(value, dict) else None


def update_evaluation(
    marketplace: str,
    listing_id: str,
    item: str,
    *,
    now: float | None = None,
    local_cache: Cache | None = None,
    **changes: Any,
) -> EvaluationRecord | None:
    """Change the status fields of a saved record, keeping its decision; None if there is none.

    ``price`` goes through :func:`apply_price`, and a new ``state`` sets ``state_changed``.
    Best effort, like :func:`record_evaluation`.
    """
    c = cache if local_cache is None else local_cache
    now = time.time() if now is None else now
    if is_cache_broken(c):
        return None
    try:
        record = _load(c, marketplace, listing_id, item)
        if record is None:
            return None
        if "price" in changes:
            apply_price(record, changes.pop("price"), now)
        state = changes.pop("state", None)
        if state is not None and state != record.state:
            record.state = state
            record.state_changed = now
        for name, value in changes.items():
            setattr(record, name, value)
        _save(c, record)
        return record
    except KeyboardInterrupt:
        raise
    except Exception:
        logger.debug("Failed to update the evaluation of %s", listing_id, exc_info=True)
        return None


def record_seen(
    marketplace: str,
    listing_id: str,
    item: str,
    price: str,
    *,
    now: float | None = None,
    local_cache: Cache | None = None,
) -> None:
    """A listing aimm decided on before is in the search results again, at this price."""
    now = time.time() if now is None else now
    update_evaluation(
        marketplace, listing_id, item, price=price, last_seen=now, now=now, local_cache=local_cache
    )


def record_evaluation(record: EvaluationRecord, *, local_cache: Cache | None = None) -> None:
    """Save a decision, replacing any earlier one for the same listing and item.

    Recording is best effort: a cache that cannot be written never stops a search.
    """
    c = cache if local_cache is None else local_cache
    if is_cache_broken(c):
        return
    try:
        old = _load(c, record.marketplace, record.id, record.item)
        if old is not None:
            for name in ("previous_price", "price_changed", "state", "state_changed", "checked"):
                setattr(record, name, getattr(old, name))
            new_price, record.price = record.price, old.price
            apply_price(record, new_price, record.time)
        record.last_seen = max(record.last_seen, record.time)
        _save(c, record)
    except KeyboardInterrupt:
        raise
    except Exception:
        logger.debug("Failed to record the evaluation of %s", record.id, exc_info=True)


def history_cutoff() -> float:
    """Epoch seconds before which records are out of the history.

    Records carry the expiry that was in effect when they were saved, so a lower
    ``evaluation_history_days`` only takes effect through this cutoff.
    """
    return time.time() - _history_days * 24 * 60 * 60


def iter_evaluations(
    *,
    since: float | None = None,
    item: str | None = None,
    stage: str | None = None,
    local_cache: Cache | None = None,
) -> Iterator[EvaluationRecord]:
    """Yield the saved records, in no particular order, optionally filtered.

    ``since`` is in epoch seconds. Records older than the history (see
    :func:`history_cutoff`) are removed instead. Yields nothing when the cache
    cannot be read.
    """
    c = cache if local_cache is None else local_cache
    if is_cache_broken(c):
        return
    try:
        keys = list(c.iterkeys())
    except KeyboardInterrupt:
        raise
    except Exception:
        logger.debug("Failed to read the evaluation history", exc_info=True)
        return
    cutoff = history_cutoff()
    for key in keys:
        if not isinstance(key, tuple) or len(key) < 4:
            continue
        if key[0] != CacheType.EVALUATIONS.value:
            continue
        try:
            value = c.get(key)  # None once the record has expired
            if not isinstance(value, dict):
                continue
            record = EvaluationRecord.from_dict(value)
            if record.time < cutoff:
                c.delete(key)
                continue
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.debug("Skipping malformed evaluation record %r", key, exc_info=True)
            continue
        if item is not None and record.item != item:
            continue
        if stage is not None and record.stage != stage:
            continue
        if since is not None and record.time < since:
            continue
        yield record


SORT_KEYS = ("time", "rating")


def filter_evaluations(
    records: Iterable[EvaluationRecord],
    *,
    since: float | None = None,
    item: str | None = None,
    stage: str | None = None,
    min_rating: int | None = None,
    text: str | None = None,
    sort: str = "time",
    descending: bool = True,
) -> List[EvaluationRecord]:
    """The matching records, sorted by ``sort`` ("time" or "rating"), newest first by default.

    ``text`` matches title, seller, location, price, reason and AI comment, ignoring case.
    Sorting by rating puts unrated listings last either way, and orders equal ratings
    newest first.
    """
    if sort not in SORT_KEYS:
        raise ValueError(f"sort must be one of {', '.join(SORT_KEYS)}")
    needle = (text or "").strip().lower()
    matched = [
        r
        for r in records
        if (since is None or r.time >= since)
        and (item is None or r.item == item)
        and (stage is None or r.stage == stage)
        and (min_rating is None or (r.rating is not None and r.rating >= min_rating))
        and (not needle or needle in _searchable(r))
    ]
    matched.sort(key=lambda r: r.time, reverse=sort == "rating" or descending)
    if sort == "rating":
        # stable sorts: rated before unrated, then by rating, keeping newest first among equals
        matched.sort(key=lambda r: r.rating or 0, reverse=descending)
        matched.sort(key=lambda r: r.rating is None)
    return matched


def _searchable(record: EvaluationRecord) -> str:
    return " ".join(
        str(x)
        for x in (
            record.title,
            record.seller,
            record.location,
            record.reason,
            record.ai_comment,
            record.price,
        )
    ).lower()
