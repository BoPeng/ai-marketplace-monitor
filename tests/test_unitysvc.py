from pathlib import Path
from unittest.mock import patch

import pytest

from ai_marketplace_monitor.ai import UnitySVCBackend, UnitySVCConfig
from ai_marketplace_monitor.config import Config

BASE = """
[marketplace.facebook]
search_city = "houston"

[user.u]
pushbullet_token = "x"

[item.bike]
search_phrases = "bike"
"""


def _load(tmp_path: Path, ai_section: str) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(BASE + ai_section)
    return Config([path])


def test_section_name_selects_unitysvc(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[ai.unitysvc]\napi_key = "svcpass_test"\n')
    assert isinstance(cfg.ai["unitysvc"], UnitySVCConfig)


def test_provider_key_selects_unitysvc(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[ai.mine]\nprovider = "UnitySVC"\napi_key = "svcpass_test"\n')
    assert isinstance(cfg.ai["mine"], UnitySVCConfig)


def test_api_key_is_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UnitySVC requires a string api_key"):
        _load(tmp_path, "[ai.unitysvc]\n")


def test_defaults_use_the_balanced_llm_platform_service() -> None:
    assert UnitySVCBackend.base_url == "https://api.svcpass.com/p/llm"
    assert UnitySVCBackend.default_model == "balanced"


def test_connect_points_the_openai_client_at_unitysvc() -> None:
    backend = UnitySVCBackend(UnitySVCConfig(name="unitysvc", api_key="svcpass_test"))
    with patch("openai.OpenAI") as client:
        backend.connect()
    assert client.call_args.kwargs["base_url"] == "https://api.svcpass.com/p/llm"
    assert client.call_args.kwargs["api_key"] == "svcpass_test"


def test_base_url_can_be_overridden() -> None:
    config = UnitySVCConfig(
        name="unitysvc", api_key="svcpass_test", base_url="https://api.staging.example/p/llm"
    )
    with patch("openai.OpenAI") as client:
        UnitySVCBackend(config).connect()
    assert client.call_args.kwargs["base_url"] == "https://api.staging.example/p/llm"
