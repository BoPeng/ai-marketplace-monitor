"""find_city: the Configure chat looks a place up in Facebook's location dialog (#441)."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterator, List
from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor import facebook
from ai_marketplace_monitor.configure import tools as tools_module
from ai_marketplace_monitor.configure.tools import ToolExecutor
from ai_marketplace_monitor.control import MonitorControl, control
from ai_marketplace_monitor.facebook import (
    FacebookLocationDialog,
    FacebookMarketplace,
    FacebookMarketplaceConfig,
    city_code_from_url,
)
from tests.configure_util import ONE_ITEM, make_ws


# --- the task queue between the web UI and the monitor
def test_browser_tasks_need_a_monitor() -> None:
    queue = MonitorControl()
    assert not queue.has_browser()
    with pytest.raises(RuntimeError, match="not running"):
        queue.submit_browser_task("find_city", place="77494").result(timeout=1)


def test_the_monitor_runs_queued_browser_tasks() -> None:
    queue = MonitorControl()
    queue.set_browser_handler(lambda name, **args: (name, args))
    done = queue.submit_browser_task("find_city", place="77494")
    failing = MonitorControl()
    failing.set_browser_handler(lambda name, **args: 1 / 0)
    broken = failing.submit_browser_task("find_city")
    cancelled = queue.submit_browser_task("find_city", place="x")
    cancelled.cancel()  # given up on before the monitor got to it
    queue.run_browser_tasks()
    failing.run_browser_tasks()
    assert done.result(timeout=1) == ("find_city", {"place": "77494"})
    with pytest.raises(ZeroDivisionError):
        broken.result(timeout=1)
    assert cancelled.cancelled()


# --- reading the dialog and the URL
@pytest.mark.parametrize(
    "url, code",
    [
        ("https://www.facebook.com/marketplace/sandiego/search/?query=ipad", "sandiego"),
        (
            "https://www.facebook.com/marketplace/112697245411076/search/?query=ipad",
            "112697245411076",
        ),
        ("https://www.facebook.com/marketplace/houston/", "houston"),
        ("https://www.facebook.com/marketplace/", None),
        ("https://www.facebook.com/marketplace/search?query=ipad", None),
        ("https://www.facebook.com/marketplace/item/123/", None),
    ],
)
def test_the_city_code_in_a_marketplace_url(url: str, code: str | None) -> None:
    assert city_code_from_url(url) == code


def test_the_place_on_the_location_button() -> None:
    page = MagicMock()
    page.locator.return_value.first.get_attribute.return_value = (
        "Location: San Diego, California, Within 10 mi"
    )
    assert FacebookLocationDialog(page).current_place() == "San Diego, California"


def test_find_city_applies_the_chosen_place(monkeypatch: pytest.MonkeyPatch) -> None:
    steps: list = []

    class FakeDialog:
        def __init__(self, page: Any, *args: Any) -> None:
            self.page = page

        def open(self) -> None:
            steps.append("open")

        def search_places(self, place: str) -> list:
            steps.append(f"search {place}")
            return ["Katy, TX 77494 · Katy, TX", "Ashdod, Israel"]

        def choose_place(self, choice: int) -> None:
            steps.append(f"choose {choice}")
            self.page.url = "https://www.facebook.com/marketplace/112697245411076/search/"

        def choose_radius(self, radius: float) -> str:
            steps.append(f"radius {radius}")
            return "20 miles"

        def radius_text(self) -> str:
            return "40 miles"

        def apply(self) -> None:
            steps.append("apply")

        def current_place(self) -> str:
            return "Katy, Texas"

        def close(self) -> None:
            steps.append("close")

    monkeypatch.setattr(facebook, "FacebookLocationDialog", FakeDialog)
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(FacebookMarketplaceConfig(name="facebook", search_city=["houston"]))
    mp.page = MagicMock(url="https://www.facebook.com/marketplace/houston/")
    found = mp.find_city("77494", radius=20)
    assert steps == ["open", "search 77494", "choose 1", "radius 20", "apply"]
    assert found == {
        "places": ["Katy, TX 77494 · Katy, TX", "Ashdod, Israel"],
        "chosen": "Katy, TX 77494 · Katy, TX",
        "search_city": "112697245411076",
        "city_name": "Katy, Texas",
        "radius": "20 miles",
    }
    with pytest.raises(ValueError, match="choice must be 1 to 2"):
        mp.find_city("77494", choice=3)
    assert steps[-1] == "close"


# --- the chat tool
@pytest.fixture
def monitor() -> Iterator[Dict[str, Any]]:
    """A stand-in monitor: a thread that runs browser tasks like the real one does."""
    calls: Dict[str, Any] = {"args": []}

    def handler(name: str, **args: Any) -> Dict[str, Any]:
        calls["args"].append(args)
        if args["place"] == "nowhere":
            return {"places": [], "chosen": None, "search_city": None}
        return {
            "places": ["San Diego, CA 92101"],
            "chosen": "San Diego, CA 92101",
            "search_city": "sandiego",
            "city_name": "San Diego, California",
            "radius": "10 miles",
        }

    control.set_browser_handler(handler)
    stop = threading.Event()

    def run() -> None:
        while not stop.is_set():
            control.run_browser_tasks()
            stop.wait(0.05)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    yield calls
    stop.set()
    thread.join()
    control.set_browser_handler(None)


def _executor(ws: Any) -> ToolExecutor:
    ex = ToolExecutor(ws)
    ex.guides_read.add("marketplace")
    return ex


def _run(scenario: Callable[[], Awaitable[Any]]) -> Any:
    """Run a coroutine on a fresh event loop in its own thread.

    Not as an async test: the Playwright tests (test_facebook.py) leave an event loop running
    in the main thread, so pytest-asyncio cannot start one there for later tests.
    """
    result: List[Any] = []
    errors: List[BaseException] = []

    def target() -> None:
        try:
            result.append(asyncio.run(scenario()))  # type: ignore[arg-type]
        except BaseException as e:
            errors.append(e)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


def test_find_city_gives_a_code_the_chat_may_save(tmp_path: Path, monitor: Dict[str, Any]) -> None:
    async def scenario() -> Any:
        ws = await make_ws(tmp_path, ONE_ITEM)
        ex = _executor(ws)
        out = await ex.call("find_city", {"place": "92101", "radius": 10})
        saved = await ex.call(
            "section_update",
            {
                "section_type": "marketplace",
                "name": "facebook",
                "values": '{"search_city": ["sandiego"], "city_name": ["San Diego, California"]}',
            },
        )
        return ws, out, saved

    ws, out, saved = _run(scenario)
    assert out["ok"] and out["search_city"] == "sandiego" and out["radius"] == "10 miles"
    assert monitor["args"] == [{"place": "92101", "choice": 1, "radius": 10}]
    assert "sandiego" in ws.found_city_codes
    assert saved["ok"], saved  # the guard against made-up codes accepts it


def _find(tmp_path: Path, place: str) -> Dict[str, Any]:
    async def scenario() -> Dict[str, Any]:
        ws = await make_ws(tmp_path, ONE_ITEM)
        return await _executor(ws).call("find_city", {"place": place})

    return _run(scenario)  # type: ignore[no-any-return]


def test_find_city_without_a_place_facebook_knows(tmp_path: Path, monitor: Dict[str, Any]) -> None:
    out = _find(tmp_path, "nowhere")
    assert not out["ok"] and "no place" in out["errors"][0]


def test_find_city_needs_the_monitor(tmp_path: Path) -> None:
    """In `aimm configure` in a terminal there is no monitor: the chat asks for a URL."""
    out = _find(tmp_path, "92101")
    assert not out["ok"] and "URL of a Marketplace search" in out["errors"][0]


def test_find_city_gives_up_when_the_monitor_is_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control.set_browser_handler(lambda name, **args: {})  # registered, but never runs the queue
    monkeypatch.setattr(tools_module, "FIND_CITY_TIMEOUT", 0.2)
    try:
        out = _find(tmp_path, "92101")
    finally:
        control.set_browser_handler(None)
        control.run_browser_tasks()  # drop the cancelled task
    assert not out["ok"] and "did not get to the lookup in time" in out["errors"][0]
