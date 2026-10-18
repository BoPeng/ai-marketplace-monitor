"""find_city: Facebook Marketplace's location code for a place, without a browser (#441)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from ai_marketplace_monitor.configure import tools as tools_module
from ai_marketplace_monitor.configure.tools import ToolExecutor
from ai_marketplace_monitor.marketplaces.facebook.location import (
    FacebookLocations,
    LocationLookupError,
    Place,
    expand_state,
)
from tests.configure_util import ONE_ITEM, make_ws
from tests.configure_util import run_in_fresh_loop as _run

# the answers Facebook gave on 2026-10-10 (shortened)
PLACES = {
    # a name alone: Los Angeles, Texas is not among Facebook's ten
    "Los Angeles": [
        (
            "Los Angeles",
            "Los Ángeles, Coahuila de Zaragoza, Mexico · 433 people checked in here",
            25.5,
            -103.4,
        ),
        ("Los Angeles, California", "City", 34.05, -118.24),
        ("Los Ángeles, Chile", "City", -37.47, -72.35),
    ],
    "Los Angeles, Texas": [
        ("Los Angeles Subdivision, Texas", "City", 27.0, -97.9),
        ("Los Angeles, La Salle County, Texas", "City", 28.4, -99.0),
    ],
    "92101": [
        ("San Diego, CA 92101", "San Diego, CA · 116 people checked in here", 32.72, -117.17)
    ],
}
CODES = {
    (25.5, -103.4): "torreon",
    (34.05, -118.24): "la",
    (-37.47, -72.35): "112677128908746",
    (27.0, -97.9): "113623475314526",
    (28.4, -99.0): "487995858630733",
    (32.72, -117.17): "sandiego",
}


# the anonymous token as Facebook's logged-out page embeds it (a made-up value)
FAKE_TOKEN_PAGE = '"LSD",[],{"token":"tok123"}'


class _Response:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text, self.status_code = text, status_code


class FakeFacebook:
    """A requests.Session that answers like Facebook's page and GraphQL endpoint."""

    def __init__(self, token_page: str | None = None, broken: bool = False) -> None:
        self.token_page = FAKE_TOKEN_PAGE if token_page is None else token_page
        self.broken = broken
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


@pytest.mark.parametrize(
    "answer, message",
    [
        # GraphQL errors arrive with HTTP 200, next to null or partial data
        ('{"errors":[{"message":"Rate limit exceeded"}],"data":null}', "Rate limit exceeded"),
        (
            '{"errors":[{"message":"Field missing"}],"data":{"city_street_search":null}}',
            "Field missing",
        ),
        ('{"data":null}', "failed"),
        ("[]", "answered unexpectedly"),
    ],
)
def test_graphql_errors_are_reported_with_facebooks_message(answer: str, message: str) -> None:
    class Answering(FakeFacebook):
        def post(self, url: str, data: Dict[str, str], **kwargs: Any) -> _Response:
            return _Response(answer)

    with pytest.raises(LocationLookupError, match=message):
        FacebookLocations(Answering()).find("92101")  # type: ignore[arg-type]


# --- the chat tool
def _tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, place: str, fake: FakeFacebook) -> Any:
    monkeypatch.setattr(tools_module, "FacebookLocations", lambda: FacebookLocations(fake))  # type: ignore[arg-type]

    async def scenario() -> Any:
        ws = await make_ws(tmp_path, ONE_ITEM)
        ex = ToolExecutor(ws)
        ex.guides_read.add("marketplace")
        out = await ex.call("find_city", {"place": place})
        saved = None
        if out.get("ok"):
            code = out["places"][-1]["facebook"]
            saved = await ex.call(
                "section_update",
                {
                    "section_type": "marketplace",
                    "name": "facebook",
                    "values": json.dumps(
                        {"search_city": [code], "city_name": [out["places"][-1]["place"]]}
                    ),
                },
            )
        return ws, out, saved

    return _run(scenario)


def test_find_city_lists_the_places_for_the_user_to_choose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, out, saved = _tool(tmp_path, monkeypatch, "Los Angeles, TX", FakeFacebook())
    assert out["ok"] and [p["facebook"] for p in out["places"]] == [
        "113623475314526",
        "487995858630733",
    ]
    assert out["places"][1]["place"] == "Los Angeles, La Salle County, Texas"
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


# --- whole conversations: the user names a place, aimm saves its code
def _converse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    steps: List[Any],
    answers: List[str],
    fake: Any = None,
) -> Any:
    from ai_marketplace_monitor.configure.agent import run_agent
    from tests.configure_util import FakeModel

    if fake is not None:
        monkeypatch.setattr(tools_module, "FacebookLocations", lambda: FacebookLocations(fake))

    async def scenario() -> Any:
        ws = await make_ws(tmp_path, ONE_ITEM, answers)
        executor = ToolExecutor(ws, only={("marketplace", "facebook")})
        executor.guides_read.add("marketplace")
        model = FakeModel(steps).bind(executor.tools_for_model(), lambda: executor.done)
        outcome = await run_agent(executor, model, "system", "opening")
        return outcome, model, (tmp_path / "config.toml").read_text(encoding="utf-8")

    return _run(scenario)


def _save_los_angeles(code: str, name: str) -> List[Any]:
    return [
        [
            (
                "section_update",
                {
                    "section_type": "marketplace",
                    "name": "facebook",
                    "values": {"search_city": [code], "city_name": [name], "radius": [40]},
                    "request": "Search Los Angeles, Texas.",
                },
            ),
            ("save", {"message": f"Searching {name}."}),
        ],
        [("finish", {"message": "Done."})],
    ]


def test_los_angeles_tx_is_saved_with_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user names the city and state: aimm looks it up and saves Facebook's code."""
    from ai_marketplace_monitor.configure.tools import Outcome

    outcome, model, written = _converse(
        tmp_path,
        monkeypatch,
        [
            [("ask_user", {"message": "Where should I search, and how far around it?"})],
            [("find_city", {"place": "Los Angeles, TX"})],
            *_save_los_angeles("113623475314526", "Los Angeles Subdivision, Texas"),
        ],
        ["Los Angeles, TX, within 40 miles", "yes"],
        FakeFacebook(),
    )
    found = model.results("find_city")[0]
    assert found["places"][0] == {
        "place": "Los Angeles Subdivision, Texas",
        "detail": "City",
        "facebook": "113623475314526",
    }
    assert outcome is Outcome.SAVED
    marketplace = tomllib.loads(written)["marketplace"]["facebook"]
    assert marketplace["search_city"] in ("113623475314526", ["113623475314526"]), written
    assert marketplace["city_name"] in (
        "Los Angeles Subdivision, Texas",
        ["Los Angeles Subdivision, Texas"],
    )


def test_a_name_alone_is_confirmed_from_facebooks_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name alone: the chat offers Facebook's places, then looks again with the state."""
    outcome, model, written = _converse(
        tmp_path,
        monkeypatch,
        [
            [("ask_user", {"message": "Where should I search?"})],
            [("find_city", {"place": "Los Angeles"})],
            [
                (
                    "ask_user",
                    {
                        "message": "Do you mean Los Angeles, California, Los Angeles in "
                        "Coahuila, Mexico, or Los Ángeles, Chile?"
                    },
                )
            ],
            [("find_city", {"place": "Los Angeles, Texas"})],
            *_save_los_angeles("113623475314526", "Los Angeles Subdivision, Texas"),
        ],
        ["Los Angeles, within 40 miles", "No, the one in Texas", "yes"],
        FakeFacebook(),
    )
    offered = model.results("find_city")[0]["places"]
    assert [p["place"] for p in offered] == [
        "Los Angeles (Los Ángeles, Coahuila de Zaragoza, Mexico)",
        "Los Angeles, California",
        "Los Ángeles, Chile",
    ]
    assert model.results("find_city")[1]["places"][0]["facebook"] == "113623475314526"
    marketplace = tomllib.loads(written)["marketplace"]["facebook"]
    assert marketplace["search_city"] in ("113623475314526", ["113623475314526"]), written


def test_places_are_labelled_with_their_region() -> None:
    """Facebook often names a place only "Los Angeles"; the label adds its region."""
    assert Place("Los Angeles, California", "City", 0, 0).label == "Los Angeles, California"
    assert (
        Place(
            "Los Angeles",
            "Los Ángeles, Coahuila de Zaragoza, Mexico · 433 people checked in here",
            0,
            0,
        ).label
        == "Los Angeles (Los Ángeles, Coahuila de Zaragoza, Mexico)"
    )
    # a street first: the region is the last part with a comma
    assert (
        Place(
            "Los Ángeles (Madrid)",
            "La Dolorosa, 2 · Los Ángeles, Spain · 9,857 people checked in here",
            0,
            0,
        ).label
        == "Los Ángeles (Madrid) (Los Ángeles, Spain)"
    )
    assert Place(
        "San Diego, CA 92101", "San Diego, CA · 116 people checked in here", 0, 0
    ).label == ("San Diego, CA 92101")


@pytest.mark.skipif(
    not __import__("os").environ.get("AIMM_LIVE_FACEBOOK"),
    reason="set AIMM_LIVE_FACEBOOK=1 to ask the real Facebook",
)
def test_los_angeles_texas_on_the_real_facebook() -> None:
    codes = {p.name: p.code for p in FacebookLocations().find("Los Angeles, TX")}
    assert codes["Los Angeles Subdivision, Texas"] == "113623475314526"
    assert codes["Los Angeles, La Salle County, Texas"] == "487995858630733"
