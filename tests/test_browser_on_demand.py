"""The monitor starts its browser only when a marketplace or the browser view needs it (#470)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List

import pytest

from ai_marketplace_monitor import monitor as mon
from ai_marketplace_monitor.control import control
from ai_marketplace_monitor.facebook import FacebookMarketplace
from ai_marketplace_monitor.utils import SleepStatus, doze


class HttpMarketplace:
    """A marketplace searched over HTTP, such as OfferUp (#467)."""

    needs_browser = False

    def __init__(self) -> None:
        self.browser: Any = None

    def set_browser(self, browser: Any) -> None:
        self.browser = browser


class BrowserMarketplace(HttpMarketplace):
    needs_browser = True


@pytest.fixture(autouse=True)
def fresh_control() -> Iterator[None]:
    control.browser_running = False
    control.browser_requested.clear()
    yield
    control.browser_running = False
    control.browser_requested.clear()


def _monitor(
    monkeypatch: pytest.MonkeyPatch, marketplaces: Dict[str, bool | None]
) -> mon.MarketplaceMonitor:
    """A monitor whose config has these marketplaces (name: enabled)."""
    monkeypatch.setattr(
        mon,
        "supported_marketplaces",
        {"facebook": FacebookMarketplace, "offerup": HttpMarketplace},
    )
    monitor = mon.MarketplaceMonitor.__new__(mon.MarketplaceMonitor)
    monitor.config = SimpleNamespace(  # type: ignore[assignment]
        marketplace={
            name: SimpleNamespace(name=name, enabled=enabled)
            for name, enabled in marketplaces.items()
        }
    )
    monitor.browser = None
    monkeypatch.setattr(mon.MarketplaceMonitor, "active_marketplaces", {})
    monitor.logger = None
    return monitor


def test_facebook_needs_the_browser() -> None:
    assert FacebookMarketplace.needs_browser


@pytest.mark.parametrize(
    "marketplaces, needed",
    [
        ({"facebook": None}, True),
        ({"facebook": True, "offerup": None}, True),
        ({"facebook": False, "offerup": None}, False),  # Facebook disabled
        ({"offerup": None}, False),
        ({}, False),
    ],
)
def test_the_browser_is_needed_only_for_a_marketplace_that_searches_with_it(
    monkeypatch: pytest.MonkeyPatch, marketplaces: Dict[str, bool | None], needed: bool
) -> None:
    assert _monitor(monkeypatch, marketplaces)._browser_needed() is needed


def test_without_a_config_no_browser_is_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = _monitor(monkeypatch, {})
    monitor.config = None
    assert not monitor._browser_needed()


def test_ensure_browser_starts_it_once_and_gives_it_to_who_needs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = _monitor(monkeypatch, {"offerup": None})
    launched: List[str] = []

    def launch() -> str:
        launched.append("browser")
        return "the browser"

    monkeypatch.setattr(monitor, "_launch_browser", launch)
    http, browser_user = HttpMarketplace(), BrowserMarketplace()
    monkeypatch.setattr(
        mon.MarketplaceMonitor, "active_marketplaces", {"offerup": http, "other": browser_user}
    )
    control.request_browser()

    monitor.ensure_browser("for the browser view")
    assert monitor.browser == "the browser"
    assert browser_user.browser == "the browser" and http.browser is None
    assert control.browser_running and not control.browser_requested.is_set()

    monitor.ensure_browser()
    assert launched == ["browser"]


def test_the_browser_view_asks_only_when_no_browser_runs() -> None:
    control.request_browser()
    assert control.browser_requested.is_set()
    control.browser_requested.clear()
    control.browser_running = True
    control.request_browser()
    assert not control.browser_requested.is_set()


def test_a_request_wakes_the_monitor() -> None:
    wake = threading.Event()
    threading.Timer(0.2, wake.set).start()
    started = time.monotonic()
    assert doze(30, wake=wake) == SleepStatus.BY_REQUEST
    assert time.monotonic() - started < 5
