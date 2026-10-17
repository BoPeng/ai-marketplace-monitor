"""The web UI's config forms offer only options their section accepts."""

import dataclasses
import re
from pathlib import Path

import pytest

from ai_marketplace_monitor.marketplaces.facebook import (
    FacebookItemConfig,
    FacebookMarketplaceConfig,
)

APP_JS = (
    Path(__file__).parents[1] / "src" / "ai_marketplace_monitor" / "webui" / "static" / "app.js"
)


def _form_keys(section: str) -> list[str]:
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index(f'"{section}": [')
    end = source.index("\n    ],", start)
    return re.findall(r'key: "(\w+)"', source[start:end])


@pytest.mark.parametrize(
    ("section", "config_class"),
    [("marketplace.facebook", FacebookMarketplaceConfig), ("item.*", FacebookItemConfig)],
)
def test_form_fields_are_options_of_their_section(section: str, config_class: type) -> None:
    # a field the section does not accept would be saved and make the config fail to load
    keys = _form_keys(section)
    assert keys
    fields = {f.name for f in dataclasses.fields(config_class)}
    assert [key for key in keys if key not in fields] == []


def test_the_offerup_form_offers_only_offerup_options() -> None:
    """The OfferUp form is the Facebook form without OFFERUP_OMIT (see app.js)."""
    from ai_marketplace_monitor.marketplaces.offerup import OfferUpMarketplaceConfig

    source = APP_JS.read_text(encoding="utf-8")
    omitted = re.findall(r'"(\w+)"', re.search(r"OFFERUP_OMIT = \[(.*?)\]", source).group(1))  # type: ignore[union-attr]
    # exactly what OfferUp lacks: an option OfferUp has (radius, say) must stay in its form
    assert sorted(omitted) == sorted(
        [
            "username",
            "password",
            "login_wait_time",
            "language",
            "category",
            "availability",
            "search_region",
            "currency",
        ]
    )
    keys = [k for k in _form_keys("marketplace.facebook") if k not in omitted]
    fields = {f.name for f in dataclasses.fields(OfferUpMarketplaceConfig)}
    assert "search_city" in keys
    assert [key for key in keys if key not in fields] == []
    # nothing OfferUp lacks is left in its form
    facebook_only = {f.name for f in dataclasses.fields(FacebookMarketplaceConfig)} - fields
    assert facebook_only <= set(omitted) | {"market_type", "request", "enabled", "monitor_config"}
