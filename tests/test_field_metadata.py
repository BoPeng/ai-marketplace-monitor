"""Field facts declared as dataclass metadata on the config classes."""

from dataclasses import fields

import pytest

from ai_marketplace_monitor.email_notify import EmailNotificationConfig
from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketplaceConfig
from ai_marketplace_monitor.marketplace import (
    Fallback,
    location_keys,
    option_fallbacks,
    resolve_option,
    site_fallbacks,
)
from ai_marketplace_monitor.notification import (
    CHANNEL,
    COMMON,
    RECIPIENT,
    PushNotificationConfig,
    fields_with_role,
)
from ai_marketplace_monitor.ntfy import NtfyNotificationConfig
from ai_marketplace_monitor.pushbullet import PushbulletNotificationConfig
from ai_marketplace_monitor.pushover import PushoverNotificationConfig
from ai_marketplace_monitor.telegram import TelegramNotificationConfig
from ai_marketplace_monitor.unitysvc_notify import UnitySVCNotificationConfig
from ai_marketplace_monitor.user import UserConfig

# the rule table that lived in marketplace.py before the facts moved onto the fields
EXPECTED_FALLBACK = {
    "ai": Fallback.NOT_NONE,
    "exclude_sellers": Fallback.NOT_NONE,
    "seller_locations": Fallback.NOT_NONE,
    "prompt": Fallback.NOT_NONE,
    "extra_prompt": Fallback.NOT_NONE,
    "rating_prompt": Fallback.NOT_NONE,
    "notify": Fallback.TRUTHY,
    "search_city": Fallback.TRUTHY,
    "city_name": Fallback.TRUTHY,
    "radius": Fallback.TRUTHY,
    "currency": Fallback.TRUTHY,
    "search_interval": Fallback.TRUTHY,
    "max_search_interval": Fallback.TRUTHY,
    "start_at": Fallback.TRUTHY,
    "max_price": Fallback.TRUTHY,
    "min_price": Fallback.TRUTHY,
    "rating": Fallback.TRUTHY,
    "availability": Fallback.TRUTHY,
    "condition": Fallback.TRUTHY,
    "date_listed": Fallback.TRUTHY,
    "delivery_method": Fallback.TRUTHY,
    "category": Fallback.TRUTHY,
    "sort_by": Fallback.TRUTHY,
}
TYPE_CLASSES = (
    EmailNotificationConfig,
    PushbulletNotificationConfig,
    PushoverNotificationConfig,
    NtfyNotificationConfig,
    TelegramNotificationConfig,
    UnitySVCNotificationConfig,
)
_BASE = {"name", "enabled", "request"}


@pytest.mark.parametrize("cls", [FacebookItemConfig, FacebookMarketplaceConfig])
def test_option_fallbacks_match_previous_table(cls: type) -> None:
    assert option_fallbacks(cls) == EXPECTED_FALLBACK


def test_site_fallbacks() -> None:
    assert site_fallbacks(FacebookItemConfig) == {
        ("ai_prompt", "min_price"): Fallback.ITEM_ONLY,
        ("ai_prompt", "max_price"): Fallback.ITEM_ONLY,
    }


def test_location_keys() -> None:
    assert set(location_keys(FacebookItemConfig)) == {
        "search_region",
        "search_city",
        "city_name",
        "radius",
        "currency",
    }


def test_resolve_option_reads_rules_from_the_item_class() -> None:
    market = FacebookMarketplaceConfig(
        name="facebook", search_city=["houston"], notify=["m"], seller_locations=["x"]
    )
    empty = FacebookItemConfig(
        name="bike", search_phrases=["bike"], notify=[], seller_locations=[]
    )
    assert resolve_option("notify", empty, market) == ["m"]  # truthy rule
    assert resolve_option("seller_locations", empty, market) == []  # not-None rule
    priced = FacebookMarketplaceConfig(name="facebook", search_city=["houston"], min_price="100")
    unpriced = FacebookItemConfig(name="bike", search_phrases=["bike"])
    assert resolve_option("min_price", unpriced, priced) == "100"
    assert resolve_option("min_price", unpriced, priced, site="ai_prompt") is None


@pytest.mark.parametrize("cls", [*TYPE_CLASSES, UserConfig])
def test_every_notification_field_has_a_role(cls: type) -> None:
    roleless = [
        f.name
        for f in fields(cls)
        if f.name not in _BASE
        and not f.name.startswith("_")
        and f.name not in ("notify_with", "remind")
        and "role" not in f.metadata
    ]
    assert roleless == []


def test_notification_roles_match_previous_lists() -> None:
    recipients = {f for cls in TYPE_CLASSES for f in fields_with_role(cls, RECIPIENT)}
    assert recipients == {"email", "telegram_chat_id", "pushover_user_key", "ntfy_topic"}
    assert set(fields_with_role(PushNotificationConfig, COMMON)) == {
        "max_retries",
        "retry_delay",
        "rate_limit_enabled",
        "instance_rate_limit",
        "global_rate_limit",
        "message_format",
        "with_description",
    }
    assert fields_with_role(TelegramNotificationConfig, CHANNEL) == ("telegram_token",)
    assert set(fields_with_role(EmailNotificationConfig, CHANNEL)) == {
        "smtp_server",
        "smtp_port",
        "smtp_username",
        "smtp_password",
        "smtp_from",
    }


def test_redeclared_fields_keep_their_role_and_defaults() -> None:
    # telegram and ntfy redeclare common fields; role and default must survive
    assert TelegramNotificationConfig(name="t").rate_limit_enabled is True
    assert TelegramNotificationConfig(name="t").global_rate_limit == 30
    assert "rate_limit_enabled" in fields_with_role(TelegramNotificationConfig, COMMON)
    assert "message_format" in fields_with_role(NtfyNotificationConfig, COMMON)
