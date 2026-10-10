"""find_city: Facebook Marketplace's location code for a place, without a browser (#441)."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List
from urllib.parse import parse_qs

import pytest

from ai_marketplace_monitor.configure import tools as tools_module
from ai_marketplace_monitor.configure.tools import ToolExecutor
from ai_marketplace_monitor.facebook_location import (
    FacebookLocations,
    LocationLookupError,
    Place,
    expand_state,
)
from tests.configure_util import ONE_ITEM, make_ws

# the answers Facebook gave on 2026-10-10 (shortened)
PLACES = {
    "Los Angeles, Texas": [
        ("Los Angeles Subdivision, Texas", "City", 27.0, -97.9),
        ("Los Angeles, La Salle County, Texas", "City", 28.4, -99.0),
    ],
    "92101": [
        ("San Diego, CA 92101", "San Diego, CA · 116 people checked in here", 32.72, -117.17)
    ],
}
CODES = {
    (27.0, -97.9): "113623475314526",
    (28.4, -99.0): "487995858630733",
    (32.72, -117.17): "sandiego",
}


class _Response:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text, self.status_code = text, status_code


class FakeFacebook:
    """A requests.Session that answers like Facebook's page and GraphQL endpoint."""

    def __init__(
        self, token_page: str = '"LSD",[],{"token":"tok123"}', broken: bool = False
    ) -> None:
        self.token_page, self.broken = token_page, broken
        self.posts: List[Dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _Response:
        return _Response(self.token_page)

    def post(self, url: str, data: Dict[str, str], **kwargs: Any) -> _Response:
        self.posts.append(data)
        if self.broken:
            return _Response(
                'for (;;);{"error":1357054,"errorSummary":"Your Request Couldn\'t be Processed"}'
            )
        variables = json.loads(data["variables"])
        if data["fb_api_req_friendly_name"] == "MarketplaceSearchAddressDataSourceQuery":
            query = variables["params"]["query"]
            edges = [
                {
                    "node": {
                        "single_line_address": name,
                        "subtitle": detail,
                        "location": {"latitude": lat, "longitude": lon},
                    }
                }
                for name, detail, lat, lon in PLACES.get(query, [])
            ]
            body: Dict[str, Any] = {
                "data": {"city_street_search": {"street_results": {"edges": edges}}}
            }
        else:
            point = variables["buy_location"]
            code = CODES[(point["latitude"], point["longitude"])]
            body = {
                "data": {
                    "viewer": {
                        "marketplace_feed_stories": {
                            "buy_location": {"marketplace_vanity_id": code, "id": "1"}
                        }
                    }
                }
            }
        return _Response(json.dumps(body))


@pytest.mark.parametrize(
    "typed, sent",
    [
        ("Houston, TX", "Houston, Texas"),
        ("Katy TX", "Katy, Texas"),
        ("Los Angeles, tx.", "Los Angeles, Texas"),
        ("San Diego, CA", "San Diego, California"),
        ("Paris", "Paris"),
        ("92101", "92101"),
        ("Berlin, DE", "Berlin, Delaware"),  # a US abbreviation wins; Facebook still lists matches
    ],
)
def test_us_state_abbreviations_are_spelled_out(typed: str, sent: str) -> None:
    """Facebook matches the start of words, so "TX" alone does not find Texas."""
    assert expand_state(typed) == sent


def test_places_and_their_codes() -> None:
    fake = FakeFacebook()
    found = FacebookLocations(fake).find("Los Angeles, TX")  # type: ignore[arg-type]
    assert [(p.name, p.code) for p in found] == [
        ("Los Angeles Subdivision, Texas", "113623475314526"),
        ("Los Angeles, La Salle County, Texas", "487995858630733"),
    ]
    first = fake.posts[0]
    assert first["fb_api_req_friendly_name"] == "MarketplaceSearchAddressDataSourceQuery"
    assert json.loads(first["variables"])["params"]["query"] == "Los Angeles, Texas"
    assert first["lsd"] == "tok123" and first["av"] == "0"  # anonymous
    assert len(fake.posts) == 3  # the search, then a code per place


def test_a_zip_code() -> None:
    found = FacebookLocations(FakeFacebook()).find("92101")  # type: ignore[arg-type]
    assert found == [
        Place(
            "San Diego, CA 92101",
            "San Diego, CA · 116 people checked in here",
            32.72,
            -117.17,
            "sandiego",
        )
    ]


def test_facebook_refusing_is_reported() -> None:
    with pytest.raises(LocationLookupError, match="Couldn't be Processed"):
        FacebookLocations(FakeFacebook(broken=True)).find("92101")  # type: ignore[arg-type]
    with pytest.raises(LocationLookupError, match="token"):
        FacebookLocations(FakeFacebook(token_page="<html>")).find("92101")  # type: ignore[arg-type]


# --- the chat tool
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


def _tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, place: str, fake: FakeFacebook) -> Any:
    monkeypatch.setattr(tools_module, "FacebookLocations", lambda: FacebookLocations(fake))  # type: ignore[arg-type]

    async def scenario() -> Any:
        ws = await make_ws(tmp_path, ONE_ITEM)
        ex = ToolExecutor(ws)
        ex.guides_read.add("marketplace")
        out = await ex.call("find_city", {"place": place})
        saved = None
        if out.get("ok"):
            code = out["places"][-1]["search_city"]
            saved = await ex.call(
                "section_update",
                {
                    "section_type": "marketplace",
                    "name": "facebook",
                    "values": json.dumps(
                        {"search_city": [code], "city_name": [out["places"][-1]["name"]]}
                    ),
                },
            )
        return ws, out, saved

    return _run(scenario)


def test_find_city_lists_the_places_for_the_user_to_choose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, out, saved = _tool(tmp_path, monkeypatch, "Los Angeles, TX", FakeFacebook())
    assert out["ok"] and [p["search_city"] for p in out["places"]] == [
        "113623475314526",
        "487995858630733",
    ]
    assert out["places"][1]["name"] == "Los Angeles, La Salle County, Texas"
    assert {"113623475314526", "487995858630733"} <= ws.found_city_codes
    assert saved["ok"], saved  # the guard against made-up codes accepts a found code


def test_find_city_without_a_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, out, _ = _tool(tmp_path, monkeypatch, "Nowhereville", FakeFacebook())
    assert not out["ok"] and "found no place" in out["errors"][0]


def test_find_city_when_facebook_does_not_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, out, _ = _tool(tmp_path, monkeypatch, "92101", FakeFacebook(broken=True))
    assert not out["ok"] and "URL of a Marketplace search" in out["errors"][0]


def test_the_request_is_a_form_post() -> None:
    """What Facebook's page sends: form fields, not JSON."""
    fake = FakeFacebook()
    FacebookLocations(fake).find("92101")  # type: ignore[arg-type]
    fields = fake.posts[0]
    assert set(fields) >= {"lsd", "doc_id", "variables", "fb_api_req_friendly_name"}
    assert parse_qs(f"doc_id={fields['doc_id']}")["doc_id"] == ["9660140454040174"]
