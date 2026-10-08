"""Daily digest (#402): composing, rendering, sending and scheduling."""

import sys
import time
import types
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Tuple

import pytest
import schedule  # type: ignore
from diskcache import Cache  # type: ignore

from ai_marketplace_monitor import digest as dg
from ai_marketplace_monitor.email_notify import EmailNotificationConfig
from ai_marketplace_monitor.monitor import DIGEST_TAG, MarketplaceMonitor
from ai_marketplace_monitor.notification import NotificationConfig
from ai_marketplace_monitor.user import UserConfig
from ai_marketplace_monitor.utils import (
    DAILY_COUNTER_EXPIRE,
    CacheType,
    CounterItem,
    counter,
    counter_period,
)

NOW = datetime(2026, 10, 8, 9, 30).timestamp()
SINCE = NOW - dg.DIGEST_PERIOD


@dataclass
class Record:
    """The fields of #401's EvaluationRecord."""

    time: float
    item: str
    stage: str
    id: str = "1"
    marketplace: str = "facebook"
    url: str = "https://www.facebook.com/marketplace/item/1/?ref=search"
    title: str = "GoPro Hero 11"
    price: str = "$200"
    location: str = "Houston, TX"
    seller: str = ""
    condition: str = ""
    rating: int | None = None
    ai_comment: str = ""
    reason: str = ""


def records() -> List[Record]:
    return [
        Record(NOW - 100, "gopro", "notified", id="1", rating=5, ai_comment="great"),
        Record(NOW - 200, "gopro", "rejected", id="2", rating=2, ai_comment="x" * 200),
        Record(NOW - 300, "gopro", "rejected", id="3", rating=3, title="Hero 9"),
        Record(NOW - 400, "gopro", "excluded", id="4", reason="keywords"),
        Record(NOW - 500, "gopro", "excluded", id="5", reason="keywords"),
        Record(NOW - 600, "gopro", "excluded", id="6", reason="out of area"),
        Record(NOW - 700, "ipad", "rejected", id="7", rating=1, title="iPad <mini>"),
        # evaluated again later: only the latest decision counts
        Record(NOW - 9000, "ipad", "rejected", id="8", rating=1),
        Record(NOW - 800, "ipad", "notified", id="8", rating=4),
        # older than 24 hours
        Record(SINCE - 10, "ipad", "notified", id="9", rating=5),
    ]


COUNTERS: Dict[str, Dict[str, int]] = {
    "gopro": {CounterItem.SEARCH_PERFORMED.value: 10, CounterItem.LISTING_EXAMINED.value: 50},
    "ipad": {CounterItem.SEARCH_PERFORMED.value: 5},
}


def test_build_digest_counts_and_groups() -> None:
    digest = dg.build_digest(records(), COUNTERS, SINCE, NOW)
    assert [x.name for x in digest.items] == ["gopro", "ipad"]
    gopro, ipad = digest.items
    assert (gopro.searches, gopro.examined, gopro.rated) == (10, 50, 3)
    assert [x.title for x in gopro.notified] == ["GoPro Hero 11"]
    # best ratings first, comment cut to about 80 characters, query string dropped
    assert [x.rating for x in gopro.rejected] == [3, 2]
    assert len(gopro.rejected[1].comment) == dg.MAX_COMMENT_LENGTH
    assert gopro.notified[0].url == "https://www.facebook.com/marketplace/item/1/"
    assert gopro.excluded == {"keywords": 2, "out of area": 1}
    # no counter: examined is at least the listings decided on
    assert (ipad.searches, ipad.examined) == (5, 2)
    assert [x.rating for x in ipad.notified] == [4]
    total = digest.total
    assert (total.searches, total.examined, len(total.notified), len(total.rejected)) == (
        15,
        52,
        2,
        3,
    )
    assert total.n_excluded == 3
    assert digest.title.endswith("2 matches")


def test_no_matches_explains_silence() -> None:
    digest = dg.build_digest([], COUNTERS, SINCE, NOW)
    assert digest.title.endswith("no matches in 15 searches")
    for fmt in ("plain_text", "markdown", "html"):
        assert "No matches today; aimm ran 15 searches." in dg.render_digest(digest, fmt)
    assert "No matches today" in dg.render_digest_email(digest)
    assert "No matches today" in dg.render_digest(digest, "plain_text", max_length=200)


def test_lists_are_capped() -> None:
    many = [
        Record(NOW - i, "gopro", "rejected", id=str(i), rating=1, title=f"t{i}") for i in range(30)
    ]
    digest = dg.build_digest(many, {}, SINCE, NOW)
    message = dg.render_digest(digest)
    assert message.count("\n- [1] ") == dg.MAX_ENTRIES
    assert "…and 10 more" in message
    assert "…and 10 more" in dg.render_digest_email(digest)


def test_render_formats() -> None:
    digest = dg.build_digest(records(), COUNTERS, SINCE, NOW)
    plain = dg.render_digest(digest)
    assert plain.startswith("Last 24 hours (")
    assert "Total: 15 searches, 52 examined" in plain
    assert "3 excluded (keywords 2, out of area 1)" in plain
    assert "- [5] GoPro Hero 11, $200\n  https://www.facebook.com/marketplace/item/1/" in plain
    assert "- [3] Hero 9, $200" in plain

    markdown = dg.render_digest(digest, "markdown")
    assert "**gopro**" in markdown
    assert "- [5] [GoPro Hero 11](https://www.facebook.com/marketplace/item/1/), $200" in markdown

    html = dg.render_digest(digest, "html")
    assert "\n" not in html
    assert "<b>gopro</b>" in html
    assert "iPad &lt;mini&gt;" in html


def test_short_channels_get_counts_and_top_matches() -> None:
    many = [
        Record(NOW - i, "gopro", "notified", id=str(i), rating=i % 5, title=f"listing {i}")
        for i in range(40)
    ]
    digest = dg.build_digest(many, COUNTERS, SINCE, NOW)
    assert len(dg.render_digest(digest, "html")) > 1024
    for fmt in ("plain_text", "markdown", "html"):
        short = dg.render_digest(digest, fmt, max_length=1024)
        assert len(short) <= 1024
        assert "Total:" in short
        assert "…and 37 more" in short
    # even the short digest is cut to the limit
    assert len(dg.render_digest(digest, "plain_text", max_length=50)) == 50


def test_email_digest() -> None:
    html = dg.render_digest_email(dg.build_digest(records(), COUNTERS, SINCE, NOW))
    assert "Daily digest" in html
    assert ".listing-table" in html  # the listing email styles
    assert "Rejected by AI (2)" in html
    # titles are escaped
    assert "iPad &lt;mini&gt;" in html


def test_daily_counters(temp_cache: Cache) -> None:
    counter.increment(CounterItem.SEARCH_PERFORMED, "gopro", local_cache=temp_cache)
    counter.increment(CounterItem.SEARCH_PERFORMED, "gopro", 2, local_cache=temp_cache)
    key = (
        CacheType.COUNTERS_DAILY.value,
        counter_period(),
        CounterItem.SEARCH_PERFORMED.value,
        "gopro",
    )
    value, expire_time = temp_cache.get(key, expire_time=True)
    assert value == 3
    assert expire_time == pytest.approx(time.time() + DAILY_COUNTER_EXPIRE, abs=60)
    assert (
        temp_cache.get((CacheType.COUNTERS.value, CounterItem.SEARCH_PERFORMED.value, "gopro"))
        == 3
    )
    # an hour older than 24 hours is not counted
    old = (CacheType.COUNTERS_DAILY.value, counter_period(time.time() - 25 * 3600), *key[2:])
    temp_cache.set(old, 100)
    assert counter.since(time.time() - dg.DIGEST_PERIOD, local_cache=temp_cache) == {
        "gopro": {CounterItem.SEARCH_PERFORMED.value: 3}
    }


def test_load_evaluations_without_and_with_401(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules makes the import fail, as it does before #401
    monkeypatch.setitem(sys.modules, "ai_marketplace_monitor.evaluations", None)
    assert dg.load_evaluations(SINCE) == []

    calls: List[Dict[str, Any]] = []

    def iter_evaluations(**kwargs: Any) -> Iterator[Record]:
        calls.append(kwargs)
        yield from records()

    module = types.ModuleType("ai_marketplace_monitor.evaluations")
    module.iter_evaluations = iter_evaluations  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ai_marketplace_monitor.evaluations", module)
    assert len(dg.load_evaluations(SINCE)) == len(records())
    assert calls == [{"since": SINCE, "local_cache": None}]


def test_user_digest_options() -> None:
    config = UserConfig(name="me", digest="8:05", digest_channels="telegram")  # type: ignore[arg-type]
    assert (config.digest, config.digest_channels) == ("08:05", ["telegram"])
    assert UserConfig(name="me", digest=False).digest is None  # type: ignore[arg-type]
    for bad in ("25:00", "8am", "08:60", 8):
        with pytest.raises(ValueError, match="digest"):
            UserConfig(name="me", digest=bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="digest_channels"):
        UserConfig(name="me", digest_channels=["sms"])


#
# sending, with fake channels
#
@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> List[Tuple[str, str, str]]:
    """Record the messages instead of sending them."""
    messages: List[Tuple[str, str, str]] = []

    def send_message(
        self: NotificationConfig, title: str, message: str, logger: Any = None
    ) -> bool:
        messages.append((self.notify_method, title, message))  # type: ignore[attr-defined]
        return True

    def send_email_message(
        self: EmailNotificationConfig,
        title: str,
        message: str,
        html: str,
        images: Any,
        logger: Any = None,
    ) -> bool:
        messages.append(("email", title, html))
        return True

    for cls in dg.channel_classes().values():
        monkeypatch.setattr(cls, "send_message", send_message)
    monkeypatch.setattr(EmailNotificationConfig, "send_email_message", send_email_message)
    monkeypatch.setattr(dg, "load_evaluations", lambda since, local_cache=None: records())
    return messages


def user(**kwargs: Any) -> UserConfig:
    return UserConfig(
        name="me",
        digest="08:00",
        pushover_user_key="u",
        pushover_api_token="t",
        telegram_token="123:abc",
        telegram_chat_id="456",
        max_retries=1,
        retry_delay=0,
        **kwargs,
    )


def test_digest_channels() -> None:
    # no email-like channel: every channel
    assert sorted(dg.digest_channels(user())) == ["pushover", "telegram"]
    with_email = user(email=["me@example.com"], smtp_password="p")
    assert list(dg.digest_channels(with_email)) == ["email"]
    chosen = user(email=["me@example.com"], smtp_password="p", digest_channels=["telegram"])
    assert list(dg.digest_channels(chosen)) == ["telegram"]


def test_send_digest_per_channel_format(sent: List[Tuple[str, str, str]]) -> None:
    digest = dg.compose_digest(SINCE, NOW)
    config = user(email=["me@example.com"], smtp_password="p")
    config.digest_channels = ["email", "pushover", "telegram"]
    assert dg.send_digest(config, digest) == {"email": True, "pushover": True, "telegram": True}
    by_channel = {channel: (title, message) for channel, title, message in sent}
    assert all(title == digest.title for title, _ in by_channel.values())
    assert "<html>" in by_channel["email"][1]
    assert "<b>Total:</b> " in by_channel["pushover"][1]
    assert len(by_channel["pushover"][1]) <= 1024
    assert "Total: " in by_channel["telegram"][1] and "<b>" not in by_channel["telegram"][1]


def test_send_due_digest_once(sent: List[Tuple[str, str, str]], temp_cache: Cache) -> None:
    config = user()
    morning = datetime(2026, 10, 8, 7, 59)
    # not due before the digest time
    assert not dg.send_due_digest(config, now=morning, local_cache=temp_cache)
    # due: sent once
    assert dg.send_due_digest(
        config, now=morning.replace(hour=8, minute=0), local_cache=temp_cache
    )
    assert len(sent) == 2
    assert temp_cache.get(dg.digest_key("me")) == "2026-10-08"
    # a restart or a config change runs the job again: not sent again
    assert not dg.send_due_digest(config, now=morning.replace(hour=11), local_cache=temp_cache)
    assert len(sent) == 2
    # missed while aimm was down the next day: sent once on the next start
    next_day = morning + timedelta(days=1, hours=5)
    assert dg.send_due_digest(config, now=next_day, local_cache=temp_cache)
    assert not dg.send_due_digest(config, now=next_day, local_cache=temp_cache)
    assert len(sent) == 4


def test_failed_digest_is_retried(
    monkeypatch: pytest.MonkeyPatch, sent: List[Tuple[str, str, str]], temp_cache: Cache
) -> None:
    monkeypatch.setattr(dg, "send_digest", lambda *args, **kwargs: {"pushover": False})
    now = datetime(2026, 10, 8, 9)
    assert not dg.send_due_digest(user(), now=now, local_cache=temp_cache)
    assert temp_cache.get(dg.digest_key("me")) is None


def test_no_digest_without_option(sent: List[Tuple[str, str, str]], temp_cache: Cache) -> None:
    config = user()
    config.digest = None
    assert not dg.send_due_digest(config, now=datetime(2026, 10, 8, 9), local_cache=temp_cache)
    config.digest, config.enabled = "08:00", False
    assert not dg.send_due_digest(config, now=datetime(2026, 10, 8, 9), local_cache=temp_cache)
    assert sent == []


def test_schedule_digests_follow_config_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[str] = []
    monkeypatch.setattr(
        "ai_marketplace_monitor.monitor.send_due_digest",
        lambda config, logger=None: calls.append(config.name),
    )
    users = {"me": user(), "other": UserConfig(name="other")}
    monitor = MarketplaceMonitor.__new__(MarketplaceMonitor)
    monitor.logger = None
    monitor.config = types.SimpleNamespace(user=users)  # type: ignore[assignment]
    schedule.clear()
    try:
        monitor.schedule_digests()
        jobs = schedule.get_jobs()
        assert [job.tags for job in jobs] == [{f"{DIGEST_TAG}me"}]
        assert jobs[0].at_time is not None and jobs[0].at_time.strftime("%H:%M") == "08:00"
        jobs[0].run()
        assert calls == ["me"]
        # the config changes: the jobs are cleared and scheduled again
        schedule.clear()
        users["me"].digest = "20:30"
        monitor.schedule_digests()
        jobs = schedule.get_jobs()
        assert len(jobs) == 1 and jobs[0].at_time is not None
        assert jobs[0].at_time.strftime("%H:%M") == "20:30"
    finally:
        schedule.clear()
