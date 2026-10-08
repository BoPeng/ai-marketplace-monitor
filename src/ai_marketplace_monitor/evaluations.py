"""A record of every listing aimm evaluated, and what it decided.

Each decision (excluded before the AI, rejected by the AI rating, or notified) is written to the
cache under ``(evaluations, marketplace, listing_id, item_name)``. A later decision about the same
listing and item overwrites the earlier one, so the history holds one row per listing and item.
Records expire after ``[monitor] evaluation_history_days`` (30 days by default).
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Iterable, Iterator, List

from diskcache import Cache  # type: ignore

from .listing import Listing
from .utils import CacheType, cache, is_cache_broken

logger = logging.getLogger(__name__)

EXCLUDED = "excluded"  # dropped before the AI: keywords, area or seller
REJECTED = "rejected"  # AI rating below the item's threshold
NOTIFIED = "notified"  # a notification was sent
STAGES = (EXCLUDED, REJECTED, NOTIFIED)

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
        names = {f.name for f in fields(cls)}
        values: Dict[str, Any] = dict.fromkeys(names, "")
        values.update({k: v for k, v in value.items() if k in names})
        values["time"] = float(values["time"] or 0)
        rating = values["rating"]
        values["rating"] = int(rating) if isinstance(rating, (int, float)) else None
        return cls(**values)

    def to_dict(self: "EvaluationRecord") -> Dict[str, Any]:
        return asdict(self)


def record_evaluation(record: EvaluationRecord, *, local_cache: Cache | None = None) -> None:
    """Save a decision, replacing any earlier one for the same listing and item.

    Recording is best effort: a cache that cannot be written never stops a search.
    """
    c = cache if local_cache is None else local_cache
    if is_cache_broken(c):
        return
    try:
        c.set(
            (CacheType.EVALUATIONS.value, record.marketplace, record.id, record.item),
            record.to_dict(),
            expire=_history_days * 24 * 60 * 60,
            tag=CacheType.EVALUATIONS.value,
        )
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
