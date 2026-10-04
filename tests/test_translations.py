from pathlib import Path

import pytest

from ai_marketplace_monitor.config import Config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(
        '[marketplace.facebook]\nsearch_city = "houston"\n'
        '[user.u]\npushbullet_token = "x"\n'
        '[item.bike]\nsearch_phrases = "bike"\n'
    )
    return Config([path])


@pytest.mark.parametrize(
    ("locale", "vehicle", "seller"),
    [
        ("es", "Información sobre este vehículo", "Descripción del vendedor"),
        ("zh", "车辆信息", "卖家描述"),
        ("sv", "Om detta fordon", "Säljarens beskrivning"),
    ],
)
def test_bundled_vehicle_headings(config: Config, locale: str, vehicle: str, seller: str) -> None:
    translator = config.translator[locale]
    assert translator("About this vehicle") == vehicle
    assert translator("Seller's description") == seller
