from pathlib import Path

import pytest

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.facebook import FacebookItemConfig

BASE = """
[marketplace.facebook]
search_city = "houston"
request = "I live in Houston"

[user.alice]
pushbullet_token = "abc"
request = "Alice gets pushbullet"

[item.bike]
search_phrases = "bike"
request = "a road bike"

[ai.openai]
api_key = "sk-test"
request = "use openai"

[notification.tg]
telegram_token = "123:abc"
telegram_chat_id = "1"
request = "telegram bot"

[region.home]
search_city = ["houston"]
request = "home region"

[monitor]
request = "defaults"
"""


def _load(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return Config([path])


def test_request_accepted_on_every_base_config_section(tmp_path: Path) -> None:
    cfg = _load(tmp_path, BASE)
    assert cfg.marketplace["facebook"].request == "I live in Houston"
    assert cfg.item["bike"].request == "a road bike"
    assert cfg.ai["openai"].request == "use openai"
    assert cfg.notification["tg"].request == "telegram bot"
    assert cfg.region["home"].request == "home region"
    assert cfg.monitor.request == "defaults"


def test_notification_request_is_not_merged_into_user(tmp_path: Path) -> None:
    # alice has no notify_with, so notification.tg is merged into her at load time
    cfg = _load(tmp_path, BASE)
    assert cfg.user["alice"].telegram_token == "123:abc"
    assert cfg.user["alice"].request == "Alice gets pushbullet"


def test_request_must_be_a_string() -> None:
    with pytest.raises(ValueError, match="request must be a string"):
        FacebookItemConfig(name="bike", search_phrases=["bike"], request=3)  # type: ignore[arg-type]


def test_request_is_not_env_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIMM_TEST_REQUEST", "expanded")
    item = FacebookItemConfig(name="bike", search_phrases=["bike"], request="${AIMM_TEST_REQUEST}")
    assert item.request == "${AIMM_TEST_REQUEST}"


def test_translation_request_is_not_a_word(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        BASE + '[translation.de]\nrequest = "Germany"\nlocale = "German"\nCondition = "Zustand"\n',
    )
    assert cfg.translator["de"].dictionary == {"Condition": "Zustand"}


def test_request_does_not_change_hash() -> None:
    plain = FacebookItemConfig(name="bike", search_phrases=["bike"])
    with_request = FacebookItemConfig(name="bike", search_phrases=["bike"], request="anything")
    assert plain.hash == with_request.hash
    other = FacebookItemConfig(name="bike", search_phrases=["scooter"])
    assert plain.hash != other.hash
