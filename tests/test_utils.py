import time
from typing import Any, Iterator, List

import pytest

from ai_marketplace_monitor import utils
from ai_marketplace_monitor.utils import convert_to_seconds, extract_price, is_substring


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
    assert extract_price("1\u00a0875\u00a0C$") == "1875"
    assert extract_price("1\u202f875\u202fC$") == "1875"
    assert extract_price("10 500 C$") == "10500"


def test_extract_price_discounted_and_original() -> None:
    # Facebook shows the current price followed by the struck-through original.
    assert extract_price("1 875 C$2 000 C$") == "1875 | 2000"


def test_extract_price_unspecified() -> None:
    assert extract_price("**unspecified**") == "**unspecified**"
    assert extract_price("") == ""


def test_extract_price_does_not_merge_across_newlines() -> None:
    # Only space, U+00A0 and U+202F are thousands separators. A newline or tab
    # separates two distinct numbers and must not be collapsed into one.
    assert extract_price("1\n875 C$") == "1 | 875"
    assert extract_price("1\t875 C$") == "1 | 875"


def test_convert_to_seconds_is_not_affected_by_a_clock_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second ticking between parsing and subtracting must not turn 1d into 86399."""
    real_localtime = time.localtime
    ticks: Iterator[int] = iter(range(1_700_000_000, 1_700_000_100))

    def ticking_localtime(*args: Any) -> time.struct_time:
        # every argument-less call sees the clock one second later
        return real_localtime(*args) if args else real_localtime(next(ticks))

    monkeypatch.setattr(utils.time, "localtime", ticking_localtime)
    assert convert_to_seconds("1d") == 86400
    assert convert_to_seconds("1h 30m") == 5400


def test_aimm_home_overrides_the_data_directory(tmp_path: Any) -> None:
    """The Docker image keeps config, cache and logs in /data through AIMM_HOME."""
    import os
    import subprocess
    import sys

    data = tmp_path / "data"
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from ai_marketplace_monitor.utils import amm_home; print(amm_home)",
        ],
        env={**os.environ, "AIMM_HOME": str(data)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == str(data)
    assert data.is_dir()
