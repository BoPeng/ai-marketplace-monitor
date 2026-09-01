from typing import List

import pytest

from ai_marketplace_monitor.utils import extract_price, is_substring


@pytest.mark.parametrize(
    "var1,var2,res",
    [
        ["b1", "AB1", True],
        (["go pro", "gopro"], "gopro hero", True),
        ('"go pro" OR gopro', "gopro hero", True),
        ('"go pro" AND gopro', "gopro hero", False),
        (["go pro", "gopro"], "something", False),
        (["go pro", "gopro"], "go pro", True),
        (["go pro", "gopro"], "gopro", True),
        (["go pro", "gopro"], "gopro hero", True),
        # literal AND works
        ("AND", " AND Camera", True),
        ('AND OR "gopro', " AND Camera", True),
        ('"gopro" OR "AND"', " AND Camera", True),
        (['"go pro" AND 11', "gopro AND 12"], "gopro hero 12", True),
        ("DJI AND Drone AND NOT Camera", "dji drone", True),
        ("DJI AND Drone AND NOT Camera", "dji drone camera", False),
        ("DJI AND Drone AND NOT Camera", "dji  camera", False),
        ("DJI AND Drone AND NOT Camera", "drone", False),
        ("DJI AND Drone AND NOT Camera", "drone from somewhere else", False),
        ("DJI AND (Drone OR Camera)", "dji drone", True),
        ("DJI AND (Drone OR Camera)", "dji camera", True),
        ("DJI AND (Drone OR Camera)", "dji drone camera", True),
        ("DJI AND (Drone OR Camera)", "drone camera from somewhere else", False),
        ("DJI AND (Drone)", "drone camera from somewhere else", False),
        ("DJI AND (Drone)", "drone DJI from somewhere else", True),
        ("DJI AND (NOT Drone)", "drone DJI from somewhere else", False),
        ("DJI AND (Drone AND from)", "drone DJI from somewhere else", True),
        ("DJI AND (Drone AND something)", "drone DJI from somewhere else", False),
        ("DJI AND (Drone OR (camera AND bad))", "drone DJI from somewhere else", True),
        ("DJI AND (Drone OR (camera AND bad))", " DJI camera from somewhere else", False),
        ("DJI AND (Drone OR (camera AND bad))", " bad DJI camera from somewhere else", True),
    ],
)
def test_is_substring(var1: List[str] | str, var2: str, res: bool) -> None:
    assert is_substring(var1, var2) == res


def test_extract_price_comma_thousands() -> None:
    # US/UK format with a comma thousands separator must be preserved unchanged.
    assert extract_price("$1,875.00") == "$1,875.00"
    assert extract_price("$999") == "$999"


def test_extract_price_space_thousands() -> None:
    # French/European locales use a (non-breaking) space as thousands separator.
    # Regression test: "1 875" used to be split and returned as "1 | 875".
    assert extract_price("1 875 C$") == "1875"
    assert extract_price("1 875 C$") == "1875"
    assert extract_price("1 875 C$") == "1875"
    assert extract_price("10 500 C$") == "10500"


def test_extract_price_discounted_and_original() -> None:
    # Facebook shows the current price followed by the struck-through original.
    assert extract_price("1 875 C$2 000 C$") == "1875 | 2000"


def test_extract_price_unspecified() -> None:
    assert extract_price("**unspecified**") == "**unspecified**"
    assert extract_price("") == ""
