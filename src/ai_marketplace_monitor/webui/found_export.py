"""Build and serialize the "found items" export from the on-disk cache.

Reads the notified/matched listings out of the diskcache and joins them with
cached listing details and AI ratings to produce CSV-ready rows.  Read-only:
no scraping and no new persistence.

Memory use is bounded to the notified subset, not the whole cache: the full
``LISTING_DETAILS`` / ``AI_INQUIRY`` namespaces (every listing ever scraped and
every AI inquiry) are never loaded wholesale.  A first pass collects the small
set of listing ids and hashes the notified rows actually reference; a second
pass loads only those.  Rows and the CSV itself are produced lazily so an
export of many records never materializes all rows or the full CSV at once.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from diskcache import Cache  # type: ignore

from ..utils import CacheType

logger = logging.getLogger(__name__)

CSV_COLUMNS: List[str] = [
    "found_at",
    "item",
    "marketplace",
    "title",
    "price",
    "rating",
    "ai_comment",
    "location",
    "seller",
    "condition",
    "notified_user",
    "url",
]

# (marketplace, listing_id, user, date, listing_hash, price)
NotifiedRow = Tuple[str, str, str, str, Optional[str], Optional[str]]

# Leading characters a spreadsheet may interpret as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _normalize_notified(value: Any) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (date, listing_hash, price) from a USER_NOTIFIED cache value.

    Handles legacy shapes: a bare date string, a 2-tuple (date, hash), or the
    current 3-tuple (date, hash, price).
    """
    if isinstance(value, str):
        return value, None, None
    if isinstance(value, (tuple, list)):
        if len(value) == 2:
            return value[0], value[1], None
        if len(value) >= 3:
            return value[0], value[1], value[2]
    return "", None, None


def _fallback_url(marketplace: str, listing_id: str) -> str:
    """Reconstruct a listing URL when its details are no longer cached."""
    if marketplace == "facebook":
        return f"https://www.facebook.com/marketplace/item/{listing_id}/"
    return ""


def _sanitize(value: str) -> str:
    """Neutralize spreadsheet formula triggers in an untrusted CSV cell.

    Listing fields (title, seller, AI comment, ...) are scraped, attacker-
    influenceable text.  A cell starting with ``= + - @`` can execute as a
    formula when opened in Excel/Sheets, so such cells are prefixed with a
    single quote (OWASP CSV-injection guidance).
    """
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _collect_needed(
    local_cache: Cache,
) -> Tuple[List[NotifiedRow], Set[Tuple[str, str]], Set[str]]:
    """First pass: the notified spine plus the ids/hashes it references.

    Only USER_NOTIFIED entries are read here, so the large LISTING_DETAILS /
    AI_INQUIRY namespaces are not loaded during this pass.
    """
    notified: List[NotifiedRow] = []
    needed_listings: Set[Tuple[str, str]] = set()
    needed_hashes: Set[str] = set()

    for key in local_cache.iterkeys():
        if not isinstance(key, tuple) or len(key) < 4:
            continue
        if key[0] != CacheType.USER_NOTIFIED.value:
            continue
        try:
            date, listing_hash, price = _normalize_notified(local_cache.get(key))
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.debug("Skipping malformed USER_NOTIFIED entry %r", key, exc_info=True)
            continue
        notified.append((key[1], key[2], key[3], date, listing_hash, price))
        needed_listings.add((key[1], key[2]))
        if listing_hash:
            needed_hashes.add(listing_hash)

    return notified, needed_listings, needed_hashes


def _load_lookups(
    local_cache: Cache,
    needed_listings: Set[Tuple[str, str]],
    needed_hashes: Set[str],
) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Second pass: load only the details and ratings the notified rows need."""
    details_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    rating_by_hash: Dict[str, Dict[str, Any]] = {}

    for key in local_cache.iterkeys():
        if not isinstance(key, tuple) or not key:
            continue
        tag = key[0]
        try:
            if tag == CacheType.LISTING_DETAILS.value:
                value = local_cache.get(key)
                if isinstance(value, dict) and "id" in value and "marketplace" in value:
                    m_id = (value["marketplace"], value["id"])
                    if m_id in needed_listings:
                        details_by_key[m_id] = value
            elif tag == CacheType.AI_INQUIRY.value and len(key) >= 4:
                if key[3] in needed_hashes:
                    value = local_cache.get(key)
                    if isinstance(value, dict):
                        rating_by_hash[key[3]] = value
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.debug("Skipping malformed %r cache entry %r", tag, key, exc_info=True)
            continue

    return details_by_key, rating_by_hash


def _to_row(
    notified: NotifiedRow,
    details_by_key: Dict[Tuple[str, str], Dict[str, Any]],
    rating_by_hash: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    """Join one notified entry with its details and rating into a CSV row."""
    marketplace, listing_id, user, date, listing_hash, price = notified
    details = details_by_key.get((marketplace, listing_id)) or {}
    rating = (rating_by_hash.get(listing_hash) if listing_hash else None) or {}
    return {
        "found_at": date or "",
        "item": details.get("name", "") or "",
        "marketplace": marketplace,
        "title": details.get("title", "") or "",
        "price": (price if price is not None else details.get("price", "")) or "",
        "rating": str(rating["score"]) if "score" in rating else "",
        "ai_comment": rating.get("comment", "") or "",
        "location": details.get("location", "") or "",
        "seller": details.get("seller", "") or "",
        "condition": details.get("condition", "") or "",
        "notified_user": user,
        "url": details.get("post_url") or _fallback_url(marketplace, listing_id),
    }


def iter_found_rows(local_cache: Cache) -> Iterator[Dict[str, str]]:
    """Yield found-item rows lazily, one per USER_NOTIFIED entry, newest first.

    Memory stays bounded to the notified subset: only the listing details and
    ratings referenced by notified items are loaded, and row dicts are produced
    one at a time rather than all at once.
    """
    notified, needed_listings, needed_hashes = _collect_needed(local_cache)
    details_by_key, rating_by_hash = _load_lookups(local_cache, needed_listings, needed_hashes)
    # Sort the small notified tuples (not full row dicts) by found date, newest first.
    notified.sort(key=lambda n: n[3] or "", reverse=True)
    for entry in notified:
        yield _to_row(entry, details_by_key, rating_by_hash)


def build_found_rows(local_cache: Cache) -> List[Dict[str, str]]:
    """Materialize all found-item rows (see :func:`iter_found_rows`)."""
    return list(iter_found_rows(local_cache))


def _drain(buffer: io.StringIO) -> str:
    """Return and clear the buffer's contents."""
    text = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return text


def iter_found_csv(rows: Iterable[Dict[str, str]]) -> Iterator[str]:
    """Yield CSV text incrementally (header first), one chunk per row.

    Cells are sanitized against spreadsheet formula injection.  ``newline=""``
    keeps the csv module's line terminators intact.
    """
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    yield _drain(buffer)
    for row in rows:
        writer.writerow({key: _sanitize(value) for key, value in row.items()})
        yield _drain(buffer)


def rows_to_csv(rows: Iterable[Dict[str, str]]) -> str:
    """Serialize rows to a single CSV string (convenience over iter_found_csv)."""
    return "".join(iter_found_csv(rows))
