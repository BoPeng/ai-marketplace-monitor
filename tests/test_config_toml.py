import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.config_toml import dump_config_toml


def test_dump_round_trips() -> None:
    cfg = {
        "monitor": {"search_interval": "1h"},
        "marketplace": {
            "facebook": {"search_city": ["houston"], "radius": [40], "enabled": False}
        },
        "user": {"me.home": {"email": "me@example.com"}},
        "item": {"bike": {"search_phrases": ["road bike"], "prompt": 'say "yes"\nthen stop'}},
    }
    text = dump_config_toml(cfg)
    assert '[user."me.home"]' in text
    assert tomllib.loads(text) == cfg
