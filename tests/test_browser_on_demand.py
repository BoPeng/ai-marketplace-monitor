"""The monitor starts its browser only when a marketplace or the browser view needs it (#470)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Tuple

import pytest

from ai_marketplace_monitor import config as aimm_config
from ai_marketplace_monitor import monitor as mon
from ai_marketplace_monitor.config import marketplace_type
from ai_marketplace_monitor.control import control
from ai_marketplace_monitor.facebook import FacebookMarketplace
from ai_marketplace_monitor.utils import SleepStatus, doze


class HttpMarketplace:
    """A marketplace searched over HTTP, such as OfferUp (#467)."""

    needs_browser = False

    def __init__(self, name: str = "", browser: Any = None, *args: Any) -> None:
        self.name = name
        self.browser = browser

    def set_browser(self, browser: Any) -> None:
        self.browser = browser

    def configure(self, config: Any, translator: Any = None) -> None:
        self.config = config


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
    monkeypatch: pytest.MonkeyPatch, marketplaces: Dict[str, Tuple[str, bool | None]]
) -> mon.MarketplaceMonitor:
    """A monitor whose config has these marketplaces (name: (market_type, enabled))."""
    monkeypatch.setitem(aimm_config.supported_marketplaces, "offerup", HttpMarketplace)  # type: ignore[arg-type]
    monitor = mon.MarketplaceMonitor.__new__(mon.MarketplaceMonitor)
    monitor.config = SimpleNamespace(  # type: ignore[assignment]
        marketplace={
            name: SimpleNamespace(
                name=name, market_type=market_type, enabled=enabled, language=None
            )
            for name, (market_type, enabled) in marketplaces.items()
        },
        item={},
        user={},
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
        ({"facebook": ("facebook", None)}, True),
        ({"mymarket": ("facebook", None)}, True),  # any section name
        ({"facebook": ("facebook", True), "offerup": ("offerup", None)}, True),
        ({"facebook": ("facebook", False), "offerup": ("offerup", None)}, False),  # disabled
        ({"offerup": ("offerup", None)}, False),
        ({}, False),
    ],
)
def test_the_browser_is_needed_only_for_a_marketplace_that_searches_with_it(
    monkeypatch: pytest.MonkeyPatch,
    marketplaces: Dict[str, Tuple[str, bool | None]],
    needed: bool,
) -> None:
    assert _monitor(monkeypatch, marketplaces)._browser_needed() is needed


def test_without_a_config_no_browser_is_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = _monitor(monkeypatch, {})
    monitor.config = None
    assert not monitor._browser_needed()


def test_ensure_browser_starts_it_once_and_gives_it_to_who_needs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = _monitor(monkeypatch, {"offerup": ("offerup", None)})
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


# ------------------------------------------------------------------ the type of a section


@pytest.mark.parametrize(
    "name, section, expected",
    [
        ("facebook", {}, "facebook"),
        ("mymarket", {}, "facebook"),  # section names are free
        ("mymarket", {"market_type": "facebook"}, "facebook"),
        ("mymarket", {"market_type": "Facebook"}, "facebook"),
        ("offerup", {}, "offerup"),  # named after a supported marketplace
        ("offerup", {"market_type": "facebook"}, "facebook"),  # market_type comes first
    ],
)
def test_the_type_of_a_marketplace_section(
    monkeypatch: pytest.MonkeyPatch, name: str, section: Dict[str, Any], expected: str
) -> None:
    monkeypatch.setitem(aimm_config.supported_marketplaces, "offerup", HttpMarketplace)  # type: ignore[arg-type]
    assert marketplace_type(name, section) == expected


def test_market_type_must_be_a_string() -> None:
    with pytest.raises(ValueError, match="market_type must be a string"):
        marketplace_type("mymarket", {"market_type": 1})


def test_a_section_with_any_name_is_searched(tmp_path: Path) -> None:
    """[marketplace.mymarket] is a Facebook marketplace, found by its type, not its name."""
    from ai_marketplace_monitor.config import Config, marketplace_class

    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[marketplace.mymarket]\nsearch_city = "houston"\n'
        '[item.bike]\nsearch_phrases = "road bike"\n'
        '[user.me]\npushbullet_token = "x"\n',
        encoding="utf-8",
    )
    config = Config([config_file])
    assert config.marketplace["mymarket"].market_type == "facebook"
    assert marketplace_class(config.marketplace["mymarket"]) is FacebookMarketplace
    assert config.item["bike"].marketplace == "mymarket"


def test_the_normalizer_keeps_a_market_type_that_matters(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_marketplace_monitor.normalize.compact import _drop_explicit_defaults

    monkeypatch.setitem(aimm_config.supported_marketplaces, "offerup", HttpMarketplace)  # type: ignore[arg-type]
    cfg = {
        "marketplace": {
            "mymarket": {"market_type": "facebook"},
            "offerup": {"market_type": "facebook"},  # without it, the section is OfferUp
        }
    }
    _drop_explicit_defaults(cfg, {})
    assert cfg["marketplace"] == {"mymarket": {}, "offerup": {"market_type": "facebook"}}


# ------------------------------------------------------------------ how the monitor uses them


def test_schedule_jobs_starts_the_browser_only_for_who_needs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = _monitor(monkeypatch, {"offerup": ("offerup", None)})
    monkeypatch.setattr(monitor, "load_config_file", lambda: monitor.config)
    monkeypatch.setattr(monitor, "load_ai_agents", lambda: None)
    monitor.keyboard_monitor = None
    launched: List[str] = []

    def launch() -> str:
        launched.append("browser")
        return "the browser"

    monkeypatch.setattr(monitor, "_launch_browser", launch)
    monitor.schedule_jobs()
    assert launched == [] and monitor.browser is None
    assert monitor.active_marketplaces["offerup"].browser is None

    # a config reload adds a Facebook marketplace, under any name
    monkeypatch.setitem(aimm_config.supported_marketplaces, "fb", BrowserMarketplace)  # type: ignore[arg-type]
    assert monitor.config is not None
    monitor.config.marketplace["mymarket"] = SimpleNamespace(
        name="mymarket", market_type="fb", enabled=None, language=None
    )
    monitor.schedule_jobs()
    assert launched == ["browser"]
    assert monitor.active_marketplaces["mymarket"].browser == "the browser"
    assert monitor.active_marketplaces["offerup"].browser is None


def test_a_browser_that_cannot_start_for_the_view_is_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = _monitor(monkeypatch, {"offerup": ("offerup", None)})
    errors: List[str] = []
    monitor.logger = SimpleNamespace(  # type: ignore[assignment]
        info=lambda *a, **k: None, error=lambda msg, *a, **k: errors.append(msg)
    )

    def launch() -> str:
        raise RuntimeError("No browser could be launched.")

    monkeypatch.setattr(monitor, "_launch_browser", launch)
    control.request_browser()
    monitor.browser_for_view()  # does not raise: the monitor keeps searching
    assert monitor.browser is None and "No browser could be launched" in errors[0]
    assert not control.browser_requested.is_set()  # not retried until the view asks again


def test_the_browser_view_asks_for_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from ai_marketplace_monitor.webui.config_api import ConfigFileService
    from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
    from ai_marketplace_monitor.webui.server import AuthState, WebUIConfig, create_app

    novnc = tmp_path / "novnc"
    novnc.mkdir()
    monkeypatch.setenv("AIMM_ENABLE_VNC", "1")
    monkeypatch.setenv("AIMM_NOVNC_DIR", str(novnc))
    monkeypatch.setenv("AIMM_VNC_PORT", "9")  # nothing listens: the bridge closes at once
    cfg = tmp_path / "config.toml"
    cfg.write_text('[marketplace.facebook]\nsearch_city = "dallas"\n', encoding="utf-8")
    handler = LogBroadcastHandler()
    app = create_app(
        WebUIConfig(config_files=[cfg], log_handler=handler),
        AuthState(),
        ConfigFileService([cfg]),
        handler,
    )
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as client:
        # the bridge to the (absent) VNC server closes at once
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/vnc", headers={"origin": "http://testserver"}
            ) as ws:
                ws.receive_bytes()
    assert control.browser_requested.is_set()
