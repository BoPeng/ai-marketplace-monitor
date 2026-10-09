import copy
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict

import pytest

from ai_marketplace_monitor.config import Config, load_config_dicts
from tests.normalize_util import EXAMPLES


def _snapshot(cfg: Config) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in vars(cfg).items():
        if is_dataclass(value) and not isinstance(value, type):
            out[key] = asdict(value)
        else:
            out[key] = {
                name: asdict(v) if is_dataclass(v) and not isinstance(v, type) else vars(v)
                for name, v in value.items()
            }
    return out


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_from_dicts_matches_file_loading(path: Path) -> None:
    system, user = load_config_dicts([path])
    assert _snapshot(Config.from_dicts(system, user)) == _snapshot(Config([path]))


def test_from_dicts_does_not_mutate_inputs() -> None:
    system, user = load_config_dicts(EXAMPLES[:1])
    system_before, user_before = copy.deepcopy(system), copy.deepcopy(user)
    Config.from_dicts(system, user)
    assert system == system_before
    assert user == user_before


def test_load_config_dicts_merges_user_files(tmp_path: Path) -> None:
    first = tmp_path / "a.toml"
    first.write_text(
        '[marketplace.facebook]\nsearch_city = "houston"\n[user.u]\npushbullet_token = "x"\n'
    )
    second = tmp_path / "b.toml"
    second.write_text('[item.bike]\nsearch_phrases = "bike"\n')
    system, user = load_config_dicts([first, second])
    assert "region" in system
    assert set(user) == {"marketplace", "user", "item"}
    assert "bike" in Config.from_dicts(system, user).item


def test_parse_error_message_kept(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("[item\n")
    with pytest.raises(ValueError, match="Error parsing config file"):
        load_config_dicts([bad])


def test_default_template_is_a_working_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first-run config works once the environment variables are set (as in Docker)."""
    import logging
    from unittest.mock import MagicMock

    from ai_marketplace_monitor.commands.common import DEFAULT_CONFIG_TEMPLATE

    monkeypatch.setenv("FACEBOOK_USERNAME", "me@example.com")
    monkeypatch.setenv("FACEBOOK_PASSWORD", "secret")
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_key")
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    logger = MagicMock(spec=logging.Logger)
    cfg = Config([path], logger)

    facebook = cfg.marketplace["facebook"]
    assert (facebook.username, facebook.password) == ("me@example.com", "secret")
    assert cfg.ai["unitysvc"].api_key == "svcpass_key"
    assert cfg.ai["unitysvc"].model == "balanced"
    me = cfg.user["me"]
    assert me.notify_with == ["unitysvc_email", "unitysvc"]
    assert me.smtp_server == "smtp.svcpass.com"
    assert me.smtp_password == "svcpass_key"
    assert me.unitysvc_api_key == "svcpass_key"
    assert me.digest_at == "08:00"
    # channel defaults shared by both notifications are not reported as overrides
    logger.warning.assert_not_called()
