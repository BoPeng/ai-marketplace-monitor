"""Build and serialize the "found items" export from the on-disk cache.

Reads the notified/matched listings out of the diskcache and joins them with
cached listing details and AI ratings to produce CSV-ready rows.  Read-only:
no scraping and no new persistence.
"""

from __future__ import annotations

import csv
import io
from typing import Dict, List

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


def rows_to_csv(rows: List[Dict[str, str]]) -> str:
    """Serialize rows to CSV text with a fixed header and column order."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()
