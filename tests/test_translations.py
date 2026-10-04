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


BASE = """
[marketplace.facebook]
search_city = "houston"

[user.u]
pushbullet_token = "x"

[item.bike]
search_phrases = "bike"
"""


def _load(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(BASE + text)
    return Config([path])


def test_translation_section_is_a_base_config() -> None:
    from ai_marketplace_monitor.utils import BaseConfig, TranslationConfig

    assert issubclass(TranslationConfig, BaseConfig)


def test_enabled_is_a_setting_not_a_word(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        '[translation.de]\nenabled = true\nlocale = "German"\nCondition = "Zustand"\n',
    )
    translator = cfg.translator["de"]
    assert translator("Condition") == "Zustand"
    assert translator.dictionary == {"Condition": "Zustand"}
    assert translator.locale == "German"


def test_disabled_translation_is_dropped(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        '[translation.de]\nenabled = false\nlocale = "German"\nCondition = "Zustand"\n',
    )
    assert "de" not in cfg.translator
    assert "es" in cfg.translator  # bundled translations still load


def test_marketplace_language_needs_an_enabled_translation(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        BASE.replace("[marketplace.facebook]\n", '[marketplace.facebook]\nlanguage = "de"\n')
        + '[translation.de]\nenabled = false\nlocale = "German"\nCondition = "Zustand"\n'
    )
    with pytest.raises(ValueError, match="Translation for language de is not supported"):
        Config([path])


def test_missing_locale_keeps_its_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must contain a locale"):
        _load(tmp_path, '[translation.de]\nCondition = "Zustand"\n')


def test_non_string_translation_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="translations must be strings"):
        _load(tmp_path, '[translation.de]\nlocale = "German"\nCondition = 3\n')
