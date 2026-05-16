"""Analytics SQLite database for marketplace listings.

Captures everything we learn about each listing — title, price (as numeric
int for analysis), location, plate, WOF/rego expiry/status, vehicle make &
model, and whether we ended up notifying — so you can run SQL against the
data later (price trends, WOF correlation, hit rate, etc.).

The DB lives at <repo>/data/analytics.sqlite by default. Override via
AIMM_ANALYTICS_DB env var.
"""

import os
import pathlib
import re
import sqlite3
import threading
from datetime import datetime
from logging import Logger
from typing import Any, Optional

_PKG_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = pathlib.Path(
    os.environ.get("AIMM_ANALYTICS_DB") or (_PKG_ROOT / "data" / "analytics.sqlite")
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    seen_at              TEXT    NOT NULL,
    marketplace          TEXT,
    listing_id           TEXT,
    item_name            TEXT,
    title                TEXT,
    price_raw            TEXT,
    price_value          REAL,
    price_currency       TEXT,
    location             TEXT,
    post_url             TEXT,
    seller               TEXT,
    description          TEXT,
    -- Algorithmic score
    score                INTEGER,
    rejection_level      TEXT,
    -- Plate & WOF/Rego
    plate                TEXT,
    plate_source         TEXT,           -- 'text' | 'ocr' | NULL
    vehicle              TEXT,           -- '1996 TOYOTA CELICA'
    colour               TEXT,
    wof_expiry           TEXT,
    wof_status           TEXT,           -- 'Current' | 'Expired' | 'Unknown'
    wof_days_remaining   INTEGER,
    rego_expiry          TEXT,
    rego_status          TEXT,
    rego_days_remaining  INTEGER,
    -- Outcome
    notified             INTEGER NOT NULL DEFAULT 0,
    skip_reason          TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_seen_at ON listings(seen_at);
CREATE INDEX IF NOT EXISTS idx_listings_listing_id ON listings(listing_id);
CREATE INDEX IF NOT EXISTS idx_listings_plate ON listings(plate);
CREATE INDEX IF NOT EXISTS idx_listings_notified ON listings(notified);
"""


_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_db_path: Optional[pathlib.Path] = None


def _get_conn(db_path: pathlib.Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    global _conn, _db_path
    with _lock:
        if _conn is not None and _db_path == db_path:
            return _conn
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        _conn = conn
        _db_path = db_path
        return _conn


_PRICE_RE = re.compile(r"([A-Z$€£¥]{0,3})\s*([\d,]+(?:\.\d{1,2})?)")


def parse_price(raw: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    """'NZ$1,900' → (1900.0, 'NZ$'). Returns (None, None) if unparseable."""
    if not raw:
        return None, None
    m = _PRICE_RE.search(raw.strip())
    if not m:
        return None, None
    currency = (m.group(1) or "").strip() or None
    try:
        value = float(m.group(2).replace(",", ""))
    except (ValueError, AttributeError):
        return None, currency
    return value, currency


def record_listing(
    *,
    listing,
    item_name: Optional[str] = None,
    score: Optional[int] = None,
    rejection_level: Optional[str] = None,
    plate: Optional[str] = None,
    plate_source: Optional[str] = None,
    wof=None,                    # WOFResult-like or None
    notified: bool = False,
    skip_reason: Optional[str] = None,
    db_path: pathlib.Path = DEFAULT_DB_PATH,
    logger: Optional[Logger] = None,
) -> Optional[int]:
    """Insert a row for this listing. Returns the new row id, or None on error."""
    try:
        price_value, price_currency = parse_price(getattr(listing, "price", None))
        row = {
            "seen_at":             datetime.now().isoformat(timespec="seconds"),
            "marketplace":         getattr(listing, "marketplace", None),
            "listing_id":          getattr(listing, "id", None),
            "item_name":           item_name,
            "title":               getattr(listing, "title", None),
            "price_raw":           getattr(listing, "price", None),
            "price_value":         price_value,
            "price_currency":      price_currency,
            "location":            getattr(listing, "location", None),
            "post_url":            getattr(listing, "post_url", None),
            "seller":              getattr(listing, "seller", None),
            "description":         getattr(listing, "description", None),
            "score":               score,
            "rejection_level":     rejection_level,
            "plate":               plate,
            "plate_source":        plate_source,
            "vehicle":             getattr(wof, "vehicle", None) if wof else None,
            "colour":              getattr(wof, "colour", None) if wof else None,
            "wof_expiry":          getattr(wof, "wof_expiry", None) if wof else None,
            "wof_status":          getattr(wof, "wof_status", None) if wof else None,
            "wof_days_remaining":  getattr(wof, "wof_days_remaining", None) if wof else None,
            "rego_expiry":         getattr(wof, "rego_expiry", None) if wof else None,
            "rego_status":         getattr(wof, "rego_status", None) if wof else None,
            "rego_days_remaining": getattr(wof, "rego_days_remaining", None) if wof else None,
            "notified":            1 if notified else 0,
            "skip_reason":         skip_reason,
        }
        cols = ", ".join(row.keys())
        placeholders = ", ".join(f":{k}" for k in row.keys())
        conn = _get_conn(db_path)
        with _lock:
            cur = conn.execute(
                f"INSERT INTO listings ({cols}) VALUES ({placeholders})", row
            )
            return cur.lastrowid
    except Exception as e:
        if logger:
            logger.debug(f"[Analytics] DB insert failed: {e}")
        return None


def query(sql: str, params: tuple = (), db_path: pathlib.Path = DEFAULT_DB_PATH) -> list[Any]:
    """Convenience query helper for ad-hoc analysis."""
    conn = _get_conn(db_path)
    with _lock:
        return list(conn.execute(sql, params))
