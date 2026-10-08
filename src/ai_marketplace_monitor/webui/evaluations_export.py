"""Rows for the web UI's Listings view and its CSV export (see ``evaluations.py``)."""

from __future__ import annotations

import time
from typing import Dict, Iterable, Iterator, List

from ..evaluations import EvaluationRecord
from .found_export import iter_csv

EVALUATION_CSV_COLUMNS: List[str] = [
    "time",
    "item",
    "marketplace",
    "stage",
    "rating",
    "reason",
    "ai_comment",
    "title",
    "price",
    "location",
    "seller",
    "condition",
    "url",
]

# the API never returns more rows than this, whatever ``limit`` asks for
MAX_LIMIT = 2000


def evaluation_to_row(record: EvaluationRecord) -> Dict[str, str]:
    """One CSV row, with the time in local time."""
    values = record.to_dict()
    row = {key: "" if value is None else str(value) for key, value in values.items()}
    row["time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.time))
    return row


def iter_evaluations_csv(records: Iterable[EvaluationRecord]) -> Iterator[str]:
    return iter_csv((evaluation_to_row(r) for r in records), EVALUATION_CSV_COLUMNS)
