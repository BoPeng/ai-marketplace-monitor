"""Whole conversations: setting up OfferUp with the configure chat (#472)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

import pytest

from ai_marketplace_monitor.configure import tools as tools_module
from ai_marketplace_monitor.configure.tools import Outcome, ToolExecutor
from ai_marketplace_monitor.marketplaces.facebook.location import FacebookLocations
from tests.configure_util import BASE, ONE_ITEM, FakeModel, make_ws, run_in_fresh_loop

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def _converse(tmp_path: Path, text: str, steps: List[Any], answers: List[str]) -> Any:
    from ai_marketplace_monitor.configure.agent import run_agent

    async def scenario() -> Any:
        ws = await make_ws(tmp_path, text, answers)
        executor = ToolExecutor(ws)
        executor.guides_read.add("marketplace")
        model = FakeModel(steps).bind(executor.tools_for_model(), lambda: executor.done)
        outcome = await run_agent(executor, model, "system", "opening")
        written = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
        return outcome, model, written

    return run_in_fresh_loop(scenario)


def test_a_new_user_sets_up_offerup_with_a_zip_code(tmp_path: Path) -> None:
    outcome, model, written = _converse(
        tmp_path,
        BASE,
        [
            [("ask_user", {"message": "Which marketplace, and where should I search?"})],
            [
                (
                    "section_update",
                    {
                        "section_type": "marketplace",
                        "name": "offerup",
                        "values": {"search_city": ["77096"], "radius": [30]},
                        "request": "OfferUp near 77096, within 30 miles.",
                    },
                ),
                ("save", {"message": "Searching OfferUp near 77096."}),
            ],
            [("finish", {"message": "Done."})],
        ],
        ["OfferUp, near 77096, within 30 miles", "yes"],
    )
    assert outcome is Outcome.SAVED
    assert model.results("save")[0]["saved"], model.results("save")
    assert written["marketplace"]["offerup"]["search_city"] == ["77096"]
    assert "market_type" not in written["marketplace"]["offerup"]  # named after its type


def test_a_facebook_user_adds_offerup_around_a_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_find_city import FakeFacebook

    monkeypatch.setattr(tools_module, "FacebookLocations", lambda: FacebookLocations(FakeFacebook()))  # type: ignore[arg-type]
    outcome, model, written = _converse(
        tmp_path,
        ONE_ITEM,
        [
            [("ask_user", {"message": "Where should OfferUp search?"})],
            [("find_city", {"place": "Los Angeles, TX"})],
            [
                (
                    "section_update",
                    {
                        "section_type": "marketplace",
                        "name": "offerup",
                        "values": {
                            "search_city": ["27.0000,-97.9000"],  # find_city's offerup value
                            "city_name": ["Los Angeles Subdivision, Texas"],
                            "radius": [20],
                        },
                    },
                ),
                ("save", {"message": "OfferUp added."}),
            ],
            [("finish", {"message": "Done."})],
        ],
        ["Los Angeles, TX, within 20 miles", "yes"],
    )
    assert outcome is Outcome.SAVED
    place = model.results("find_city")[0]["places"][0]
    assert place["offerup"] == "27.0000,-97.9000"
    saved = model.results("save")[0]
    assert saved["saved"], saved
    # the item that names no marketplace now also searches OfferUp, and the user is told
    assert any("[item.example] names no marketplace" in n for n in saved["shown_to_user"])
    assert written["marketplace"]["offerup"]["search_city"] == ["27.0000,-97.9000"]
    assert written["marketplace"]["facebook"]["search_city"] == "houston"  # unchanged
