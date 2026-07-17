"""Build and serialize the "found items" export from the on-disk cache.

Reads the notified/matched listings out of the diskcache and joins them with
cached listing details and AI ratings to produce CSV-ready rows.  Read-only:
no scraping and no new persistence.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional, Tuple

from diskcache import Cache  # type: ignore

from ..utils import CacheType

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


def build_found_rows(local_cache: Cache) -> List[Dict[str, str]]:
    """Join notified items with details and ratings into CSV-ready rows.

    Emits one row per USER_NOTIFIED entry (i.e. per listing per user), sorted
    by found_at descending.  Malformed or legacy cache entries are skipped.
    """
    details_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    rating_by_hash: Dict[str, Dict[str, Any]] = {}
    notified: List[Tuple[str, str, str, str, Optional[str], Optional[str]]] = []

    for key in local_cache.iterkeys():
        if not isinstance(key, tuple) or not key:
            continue
        tag = key[0]
        try:
            if tag == CacheType.LISTING_DETAILS.value:
                value = local_cache.get(key)
                if isinstance(value, dict) and "id" in value and "marketplace" in value:
                    details_by_key[(value["marketplace"], value["id"])] = value
            elif tag == CacheType.AI_INQUIRY.value and len(key) >= 4:
                value = local_cache.get(key)
                if isinstance(value, dict):
                    rating_by_hash[key[3]] = value
            elif tag == CacheType.USER_NOTIFIED.value and len(key) >= 4:
                date, listing_hash, price = _normalize_notified(local_cache.get(key))
                notified.append((key[1], key[2], key[3], date, listing_hash, price))
        except KeyboardInterrupt:
            raise
        except Exception:
            continue

    rows: List[Dict[str, str]] = []
    for marketplace, listing_id, user, date, listing_hash, price in notified:
        details = details_by_key.get((marketplace, listing_id)) or {}
        rating = (rating_by_hash.get(listing_hash) if listing_hash else None) or {}
        rows.append(
            {
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
        )

    rows.sort(key=lambda r: r["found_at"], reverse=True)
    return rows


def rows_to_csv(rows: List[Dict[str, str]]) -> str:
    """Serialize rows to CSV text with a fixed header and column order."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()
