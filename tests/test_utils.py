from typing import List

import pytest

from ai_marketplace_monitor.utils import is_substring


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
