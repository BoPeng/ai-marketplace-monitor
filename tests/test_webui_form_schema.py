"""The web UI's config forms offer only options their section accepts."""

import dataclasses
import re
from pathlib import Path

import pytest

from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketplaceConfig

APP_JS = Path(__file__).parents[1] / "src" / "ai_marketplace_monitor" / "webui" / "static" / "app.js"


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
