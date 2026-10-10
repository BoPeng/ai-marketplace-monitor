"""Search radius: Facebook ignores it in the URL, so aimm sets it in the location dialog (#441)."""

from __future__ import annotations

from typing import Any, List
from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor import facebook
from ai_marketplace_monitor.facebook import (
    FacebookItemConfig,
    FacebookMarketplace,
    FacebookMarketplaceConfig,
    nearest_radius,
    radius_from_label,
)


def test_the_radius_on_the_location_button_and_in_the_dialog() -> None:
    assert radius_from_label("Location: Houston, Texas, Within 40 mi") == 40
    assert radius_from_label("Location: Austin, Texas, Within 6 mi") == 6
    assert radius_from_label("Location: Berlin, Within 250 km") == 250
    assert radius_from_label("1 mile") == 1
    assert radius_from_label("500 miles") == 500
    assert radius_from_label("Location: Houston, Texas") is None


@pytest.mark.parametrize(
    "radius, expected",
    [(40, 40), (45, 40), (30, 40), (42, 40), (805, 500), (3, 2), (0.5, 1), (300, 250)],
)
def test_the_nearest_radius_facebook_offers(radius: float, expected: int) -> None:
    assert nearest_radius(radius) == expected


def _search_urls(monkeypatch: pytest.MonkeyPatch, **config: Any) -> List[str]:
    urls: List[str] = []
    monkeypatch.setattr(facebook.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        facebook, "FacebookSearchResultPage", lambda *a, **k: MagicMock(get_listings=lambda: [])
    )
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(FacebookMarketplaceConfig(name="facebook", **config))
    mp.page = MagicMock()
    monkeypatch.setattr(mp, "goto_url", urls.append)
    monkeypatch.setattr(mp, "recover_login", lambda: False)
    monkeypatch.setattr(mp, "set_search_radius", lambda radius: False)
    list(mp.search(FacebookItemConfig(name="ipad", search_phrases=["ipad"])))
    return urls


def test_each_city_has_its_own_search_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """The options of one city no longer pile up in the next city's URL."""
    urls = _search_urls(
        monkeypatch,
        search_city=["houston", "dallas", "austin"],
        radius=[100, 50, 25],
        max_price="300",
    )
    assert urls == [
        "https://www.facebook.com/marketplace/houston/search?query=ipad&maxPrice=300",
        "https://www.facebook.com/marketplace/dallas/search?query=ipad&maxPrice=300",
        "https://www.facebook.com/marketplace/austin/search?query=ipad&maxPrice=300",
    ]


def test_a_new_radius_reloads_the_search(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: List[str] = []
    monkeypatch.setattr(facebook.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        facebook, "FacebookSearchResultPage", lambda *a, **k: MagicMock(get_listings=lambda: [])
    )
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(
        FacebookMarketplaceConfig(
            name="facebook", search_city=["houston", "dallas"], radius=[10, 10]
        )
    )
    mp.page = MagicMock()
    monkeypatch.setattr(mp, "goto_url", urls.append)
    monkeypatch.setattr(mp, "recover_login", lambda: False)
    asked: List[int] = []

    # the first city changes the radius, the second finds it already set
    def set_radius(radius: int) -> bool:
        asked.append(radius)
        return len(asked) == 1

    monkeypatch.setattr(mp, "set_search_radius", set_radius)
    list(mp.search(FacebookItemConfig(name="ipad", search_phrases=["ipad"])))
    assert asked == [10, 10]
    assert [u.split("/marketplace/")[1].split("/")[0] for u in urls] == [
        "houston",
        "houston",
        "dallas",
    ]


class _FakeLocator:
    def __init__(self, page: "_FakePage", what: str) -> None:
        self.page, self.what = page, what

    @property
    def first(self) -> "_FakeLocator":
        return self

    def get_attribute(self, name: str, timeout: int = 0) -> str:
        return self.page.label

    def click(self, timeout: int = 0) -> None:
        self.page.clicks.append(self.what)
        if self.what.startswith("option:"):
            self.page.label = f"Location: Houston, Texas, Within {self.what[7:]}"

    def get_by_role(self, role: str, name: str = "", exact: bool = False) -> "_FakeLocator":
        return _FakeLocator(self.page, f"{role}:{name}" if name else role)

    def filter(self, has_text: str = "") -> "_FakeLocator":
        return _FakeLocator(self.page, f"{self.what}:{has_text}")

    def all_inner_texts(self) -> List[str]:
        return self.page.choices


class _FakePage:
    def __init__(self, label: str, choices: List[str]) -> None:
        self.label, self.choices = label, choices
        self.clicks: List[str] = []
        self.keyboard = MagicMock()

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, "location button")

    def get_by_role(self, role: str, name: str = "", exact: bool = False) -> _FakeLocator:
        return _FakeLocator(self, f"{role}:{name}" if name else role)

    def wait_for_timeout(self, ms: int) -> None:
        pass


CHOICES = [f"{n} mile{'s' if n > 1 else ''}" for n in (1, 2, 5, 10, 20, 40, 60, 80, 100, 250, 500)]


def _marketplace(page: _FakePage) -> FacebookMarketplace:
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(FacebookMarketplaceConfig(name="facebook", search_city=["houston"]))
    mp.page = page  # type: ignore[assignment]
    return mp


def test_the_radius_is_left_alone_when_it_already_matches() -> None:
    page = _FakePage("Location: Houston, Texas, Within 40 mi", CHOICES)
    assert _marketplace(page).set_search_radius(42) is False
    assert page.clicks == []  # the dialog was not even opened


def test_a_different_radius_is_chosen_and_applied() -> None:
    page = _FakePage("Location: Houston, Texas, Within 40 mi", CHOICES)
    assert _marketplace(page).set_search_radius(10) is True
    assert page.clicks == [
        "location button",
        "combobox:Radius",
        "option:10 miles",
        "button:Apply",
    ]
    assert page.label.endswith("Within 10 miles")


def test_a_radius_that_cannot_be_set_does_not_stop_the_search() -> None:
    page = _FakePage("Location: Houston, Texas, Within 40 mi", [])  # no choices in the dialog
    assert _marketplace(page).set_search_radius(10) is False
    page.keyboard.press.assert_called_with("Escape")


def test_a_recovered_login_reapplies_the_radius(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: List[str] = []
    monkeypatch.setattr(facebook.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        facebook, "FacebookSearchResultPage", lambda *a, **k: MagicMock(get_listings=lambda: [])
    )
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(FacebookMarketplaceConfig(name="facebook", search_city=["houston"], radius=[10]))
    mp.page = MagicMock()
    monkeypatch.setattr(mp, "goto_url", urls.append)
    monkeypatch.setattr(mp, "recover_login", lambda: True)
    asked: List[int] = []

    def set_radius(radius: int) -> bool:
        asked.append(radius)
        # Before login the dialog was unavailable; afterward the radius changes.
        return len(asked) == 2

    monkeypatch.setattr(mp, "set_search_radius", set_radius)
    list(mp.search(FacebookItemConfig(name="ipad", search_phrases=["ipad"])))
    assert asked == [10, 10]
    assert urls == ["https://www.facebook.com/marketplace/houston/search?query=ipad"] * 3
