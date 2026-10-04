from ai_marketplace_monitor.normalize.model import (
    COMMON_OPTIONS,
    Change,
    describe_changes,
    order_config,
)
from ai_marketplace_monitor.utils import is_sensitive_key
from tests.normalize_util import dumps


def test_is_sensitive_key() -> None:
    assert is_sensitive_key("smtp_password")
    assert is_sensitive_key("telegram_token")
    assert is_sensitive_key("username")
    assert not is_sensitive_key("email")


def test_common_options_include_facebook_and_generic_options() -> None:
    assert {"notify", "ai", "search_region", "sort_by", "seller_locations"} <= set(COMMON_OPTIONS)
    assert "search_phrases" not in COMMON_OPTIONS
    assert "username" not in COMMON_OPTIONS


def test_type_order_is_fixed_and_within_type_order_kept() -> None:
    cfg = {
        "item": {"zeta": {"search_phrases": "z"}, "alpha": {"search_phrases": "a"}},
        "user": {"u": {"email": "e"}},
        "marketplace": {"facebook": {}},
    }
    out = order_config(cfg)
    assert list(out) == ["marketplace", "user", "item"]
    assert list(out["item"]) == ["zeta", "alpha"]


def test_key_order_request_enabled_then_declared_fields() -> None:
    cfg = {
        "item": {
            "bike": {
                "description": "d",
                "search_phrases": "bike",
                "enabled": True,
                "request": "r",
                "notify": ["u"],
            }
        }
    }
    item = order_config(cfg)["item"]["bike"]
    assert list(item) == ["request", "enabled", "notify", "search_phrases", "description"]


def test_monitor_is_a_flat_section() -> None:
    out = order_config({"monitor": {"proxy_bypass": "x", "request": "r"}})
    assert list(out["monitor"]) == ["request", "proxy_bypass"]


def test_translation_settings_first_then_words_in_input_order() -> None:
    cfg = {
        "translation": {
            "de": {"Details": "Details", "Condition": "Zustand", "locale": "de_DE", "request": "r"}
        }
    }
    assert list(order_config(cfg)["translation"]["de"]) == [
        "request",
        "locale",
        "Details",
        "Condition",
    ]


def test_describe_changes_reports_set_remove_add_and_masks_secrets() -> None:
    before = {"user": {"u": {"email": "e", "smtp_password": "old"}}}
    after = {
        "user": {"u": {"email": "e2", "smtp_password": "new"}},
        "notification": {"email": {"smtp_server": "s"}},
    }
    changes = describe_changes(before, after)
    assert Change("user.u", "set", "email", "email: 'e' -> 'e2'") in changes
    assert Change("user.u", "set", "smtp_password", "smtp_password: '<REDACTED>' -> '<REDACTED>'") in changes
    assert Change("notification.email", "add", None, "new section") in changes


def test_describe_changes_reports_pure_reordering() -> None:
    before = {"item": {"b": {"search_phrases": "x", "notify": ["u"]}}}
    after = {"item": {"b": {"notify": ["u"], "search_phrases": "x"}}}
    assert dumps(before) != dumps(after)
    assert describe_changes(before, after) == [
        Change("*", "set", None, "reordered sections and keys")
    ]


def test_describe_changes_uses_notes() -> None:
    changes = describe_changes(
        {"item": {"b": {}}}, {"item": {"b": {"notify": ["u"]}}}, {("item.b", "notify"): "why"}
    )
    assert changes == [Change("item.b", "set", "notify", "why")]
