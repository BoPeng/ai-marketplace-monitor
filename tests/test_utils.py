"""Tests for ai_marketplace_monitor.utils helpers."""

from ai_marketplace_monitor.utils import extract_price


def test_extract_price_comma_thousands() -> None:
    # US/UK format with comma thousands separator must be preserved unchanged.
    assert extract_price("$1,875.00") == "$1,875.00"
    assert extract_price("$999") == "$999"


def test_extract_price_space_thousands() -> None:
    # French/European format uses a (non-breaking) space as thousands separator.
    # Regression test: previously "1 875" was split into "1 | 875".
    assert extract_price("1 875 C$") == "1875"
    assert extract_price("1 875 C$") == "1875"  # non-breaking space
    assert extract_price("10 500 C$") == "10500"


def test_extract_price_discounted_and_original() -> None:
    # Facebook shows the current price plus the struck-through original,
    # e.g. "1 875 C$2 000 C$" -> current | original.
    assert extract_price("1 875 C$2 000 C$") == "1875 | 2000"


def test_extract_price_unspecified() -> None:
    assert extract_price("**unspecified**") == "**unspecified**"
    assert extract_price("") == ""
