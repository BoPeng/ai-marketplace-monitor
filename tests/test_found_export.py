"""Tests for the Web UI found-items CSV export."""

from __future__ import annotations

import csv
import io
from typing import Dict, List

from ai_marketplace_monitor.webui.found_export import CSV_COLUMNS, rows_to_csv


def _parse(text: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_rows_to_csv_empty_has_header_only() -> None:
    text = rows_to_csv([])
    lines = text.splitlines()
    assert lines[0].split(",") == CSV_COLUMNS
    assert len(lines) == 1


def test_rows_to_csv_writes_row_and_escapes() -> None:
    row = {c: "" for c in CSV_COLUMNS}
    row["title"] = 'Chair, "comfy"'
    row["price"] = "$40"
    text = rows_to_csv([row])
    parsed = _parse(text)
    assert len(parsed) == 1
    assert parsed[0]["title"] == 'Chair, "comfy"'
    assert parsed[0]["price"] == "$40"
