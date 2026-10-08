"""Daily digest (#402): composing, rendering, sending and scheduling."""

import time
import types
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
from zoneinfo import ZoneInfo

import pytest
import schedule  # type: ignore
from diskcache import Cache  # type: ignore

from ai_marketplace_monitor import digest as dg
from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.email_notify import EmailNotificationConfig
from ai_marketplace_monitor.evaluations import (
    EXCLUDED,
    NOTIFIED,
    REJECTED,
    EvaluationRecord,
    iter_evaluations,
    record_evaluation,
    set_history_days,
)
from ai_marketplace_monitor.monitor import DIGEST_TAG, MarketplaceMonitor
from ai_marketplace_monitor.notification import NotificationConfig
from ai_marketplace_monitor.user import UserConfig
from ai_marketplace_monitor.utils import (
    DAILY_COUNTER_EXPIRE,
    BrokenCache,
    CacheType,
    CounterItem,
    counter,
    counter_minute,
)

NOW = datetime(2026, 10, 8, 9, 30).timestamp()
SINCE = NOW - dg.DIGEST_PERIOD


def rec(
    time: float,
    item: str,
    stage: str,
    listing_id: str = "1",
    url: str = "https://www.facebook.com/marketplace/item/1/?ref=search",
    title: str = "GoPro Hero 11",
    price: str = "$200",
    location: str = "Houston, TX",
    rating: int | None = None,
    ai_comment: str = "",
    reason: str = "",
) -> EvaluationRecord:
    return EvaluationRecord(
        time=time,
        item=item,
        marketplace="facebook",
        id=listing_id,
        url=url,
        title=title,
        price=price,
        location=location,
        seller="",
        condition="",
        stage=stage,
        rating=rating,
        ai_comment=ai_comment,
        reason=reason,
    )


def records() -> List[EvaluationRecord]:
    return [
        rec(NOW - 100, "gopro", "notified", listing_id="1", rating=5, ai_comment="great"),
        rec(NOW - 200, "gopro", "rejected", listing_id="2", rating=2, ai_comment="x" * 200),
        rec(NOW - 300, "gopro", "rejected", listing_id="3", rating=3, title="Hero 9"),
        rec(NOW - 400, "gopro", "excluded", listing_id="4", reason="keywords"),
        rec(NOW - 500, "gopro", "excluded", listing_id="5", reason="keywords"),
        rec(NOW - 600, "gopro", "excluded", listing_id="6", reason="out of area"),
        rec(NOW - 700, "ipad", "rejected", listing_id="7", rating=1, title="iPad <mini>"),
        # evaluated again later: only the latest decision counts
        rec(NOW - 9000, "ipad", "rejected", listing_id="8", rating=1),
        rec(NOW - 800, "ipad", "notified", listing_id="8", rating=4),
        # older than 24 hours
        rec(SINCE - 10, "ipad", "notified", listing_id="9", rating=5),
    ]


COUNTERS: Dict[str, Dict[str, int]] = {
    "gopro": {CounterItem.SEARCH_PERFORMED.value: 10},
    "ipad": {CounterItem.SEARCH_PERFORMED.value: 5},
}


def test_build_digest_counts_and_groups() -> None:
    digest = dg.build_digest(records(), COUNTERS, SINCE, NOW)
    assert [x.name for x in digest.items] == ["gopro", "ipad"]
    gopro, ipad = digest.items
    assert (gopro.searches, gopro.evaluated) == (10, 6)
    assert [x.title for x in gopro.notified] == ["GoPro Hero 11"]
    # best ratings first, comment cut to about 80 characters, query string dropped
    assert [x.rating for x in gopro.rejected] == [3, 2]
    assert len(gopro.rejected[1].comment) == dg.MAX_COMMENT_LENGTH
    assert gopro.notified[0].url == "https://www.facebook.com/marketplace/item/1/"
    assert gopro.excluded == {"keywords": 2, "out of area": 1}
    assert (ipad.searches, ipad.evaluated) == (5, 2)
    assert [x.rating for x in ipad.notified] == [4]
    total = digest.total
    assert (total.searches, total.evaluated, len(total.notified), len(total.rejected)) == (
        15,
        8,
        2,
        3,
    )
    assert total.n_excluded == 3
    assert digest.title.endswith("2 matches")


def test_no_matches_explains_silence() -> None:
    digest = dg.build_digest([], COUNTERS, SINCE, NOW)
    assert digest.title.endswith("no matches in 15 searches")
    for fmt in ("plain_text", "markdown", "html"):
        assert "No matches today; aimm ran 15 searches." in dg.render_phone_digest(digest, fmt)
    text, html = dg.render_email_digest(digest)
    assert "No matches today" in text and "No matches today" in html


def test_email_lists_are_capped() -> None:
    many = [
        rec(NOW - i, "gopro", "rejected", listing_id=str(i), rating=1, title=f"t{i}")
        for i in range(30)
    ]
    text, html = dg.render_email_digest(dg.build_digest(many, {}, SINCE, NOW))
    assert text.count("\n- [1] ") == dg.MAX_ENTRIES
    assert "…and 10 more" in text and "…and 10 more" in html


def test_email_digest() -> None:
    text, html = dg.render_email_digest(dg.build_digest(records(), COUNTERS, SINCE, NOW))
    assert text.startswith("Listings evaluated in the last 24 hours (")
    assert "Total: 15 searches, 8 listings evaluated" in text
    assert "3 excluded (keywords 2, out of area 1)" in text
    assert "- [5] GoPro Hero 11, $200\n  https://www.facebook.com/marketplace/item/1/" in text
    assert "- [3] Hero 9, $200" in text
    assert "Daily digest" in html
    assert ".listing-table" in html  # the listing email styles
    assert "Listings evaluated" in html and "By item" in html  # summary and per-item tables
    assert "Rejected by AI (2)" in html
    assert 'href="https://www.facebook.com/marketplace/item/1/"' in html
    # titles are escaped
    assert "iPad &lt;mini&gt;" in html


def test_phone_digest() -> None:
    many = [
        rec(NOW - i, "gopro", "notified", listing_id=str(i), rating=i % 5, title="x" * 200)
        for i in range(40)
    ]
    digest = dg.build_digest(many, COUNTERS, SINCE, NOW)
    plain = dg.render_phone_digest(digest)
    assert plain.startswith("Last 24 h: 15 searches, 40 listings evaluated, 40 notified,")
    assert plain.count("\n- [4] ") == dg.PHONE_ENTRIES
    assert "…and 37 more" in plain
    markdown = dg.render_phone_digest(digest, "markdown")
    assert "- [4] [" in markdown and "](https://www.facebook.com/marketplace/item/1/)" in markdown
    html = dg.render_phone_digest(digest, "html")
    assert "\n" not in html and "<a href=" in html
    for message in (plain, markdown, html):
        assert len(message) <= dg.PHONE_MAX_LENGTH < 1024
    # a listing with absurdly long values is cut to the limit
    huge = [rec(NOW, "gopro", "notified", rating=5, price="$" * 2000)]
    assert len(dg.render_phone_digest(dg.build_digest(huge, {}, SINCE, NOW), "html")) == (
        dg.PHONE_MAX_LENGTH
    )


def test_daily_counters(temp_cache: Cache) -> None:
    counter.increment(CounterItem.SEARCH_PERFORMED, "gopro", local_cache=temp_cache)
    counter.increment(CounterItem.SEARCH_PERFORMED, "gopro", 2, local_cache=temp_cache)
    # only the counters the digest uses are kept per minute
    counter.increment(CounterItem.LISTING_EXAMINED, "gopro", 5, local_cache=temp_cache)
    assert [k[2] for k in temp_cache.iterkeys() if k[0] == CacheType.COUNTERS_DAILY.value] == [
        CounterItem.SEARCH_PERFORMED.value
    ]
    key = (
        CacheType.COUNTERS_DAILY.value,
        counter_minute(),
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
    # a minute older than 24 hours is not counted
    old = (CacheType.COUNTERS_DAILY.value, counter_minute(time.time() - 25 * 3600), *key[2:])
    temp_cache.set(old, 100)
    assert counter.since(time.time() - dg.DIGEST_PERIOD, local_cache=temp_cache) == {
        "gopro": {CounterItem.SEARCH_PERFORMED.value: 3}
    }


def test_search_counts_cover_the_last_24_hours_to_the_minute(temp_cache: Cache) -> None:
    """A digest at 10:30:20 counts the searches from 10:30 the day before, not from 10:00."""
    since = datetime(2026, 10, 7, 10, 30, 20).timestamp()
    for when, n in (
        (datetime(2026, 10, 7, 10, 5), 100),  # in the same hour, before the window
        (datetime(2026, 10, 7, 10, 29, 59), 10),  # the minute before
        (datetime(2026, 10, 7, 10, 30, 5), 1),  # the minute of `since`: counted
        (datetime(2026, 10, 8, 10, 30), 2),
    ):
        key = (
            CacheType.COUNTERS_DAILY.value,
            counter_minute(when.timestamp()),
            CounterItem.SEARCH_PERFORMED.value,
            "gopro",
        )
        temp_cache.set(key, n)
    assert counter.since(since, local_cache=temp_cache) == {
        "gopro": {CounterItem.SEARCH_PERFORMED.value: 3}
    }
    # up to, not including, the minute of `until`: windows that meet do not overlap
    until = datetime(2026, 10, 8, 10, 30).timestamp()
    assert counter.since(since, until, local_cache=temp_cache) == {
        "gopro": {CounterItem.SEARCH_PERFORMED.value: 1}
    }


def test_search_counts_when_daylight_saving_time_ends(
    monkeypatch: pytest.MonkeyPatch, temp_cache: Cache
) -> None:
    """01:30 happens twice in Chicago on 2026-11-01; the two are counted apart."""
    chicago = ZoneInfo("America/Chicago")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=chicago).timestamp()  # CDT
    second = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=chicago).timestamp()  # CST
    assert second - first == 60 * 60
    for when, n in ((first, 1), (second, 2)):
        monkeypatch.setattr(time, "time", lambda when=when: when)
        counter.increment(CounterItem.SEARCH_PERFORMED, "gopro", n, local_cache=temp_cache)
    monkeypatch.undo()
    searches = CounterItem.SEARCH_PERFORMED.value
    assert counter.since(first, local_cache=temp_cache) == {"gopro": {searches: 3}}
    assert counter.since(first, second, local_cache=temp_cache) == {"gopro": {searches: 1}}
    assert counter.since(first + 30 * 60, local_cache=temp_cache) == {"gopro": {searches: 2}}


def test_broken_cache_has_no_records(tmp_path: Path) -> None:
    broken = BrokenCache(tmp_path, ValueError("malformed"))
    assert dg.load_evaluations(SINCE, local_cache=broken) == []


HOUR = 60 * 60


def test_digest_from_recorded_evaluations(temp_cache: Cache) -> None:
    """The digest of records saved by record_evaluation, as aimm saves them."""
    now = time.time()
    saved = [
        # gopro: 2 notified, 2 rejected, 3 excluded (2 by keyword), 1 more than 24 hours ago
        rec(now - 1 * HOUR, "gopro", NOTIFIED, listing_id="g1", rating=5, ai_comment="Great deal"),
        rec(
            now - 2 * HOUR,
            "gopro",
            NOTIFIED,
            listing_id="g2",
            title="GoPro 10",
            price="$180 | $250",
        ),
        rec(
            now - 3 * HOUR,
            "gopro",
            REJECTED,
            listing_id="g3",
            rating=2,
            ai_comment="Only the case is for sale.",
            reason="rating 2 < 3: Only the case is for sale.",
        ),
        rec(now - 4 * HOUR, "gopro", REJECTED, listing_id="g4", rating=1, ai_comment="Broken."),
        rec(now - 5 * HOUR, "gopro", EXCLUDED, listing_id="g5", reason="excluded keyword: broken"),
        rec(
            now - 6 * HOUR,
            "gopro",
            EXCLUDED,
            listing_id="g6",
            reason="excluded keyword: parts, case",
        ),
        rec(now - 7 * HOUR, "gopro", EXCLUDED, listing_id="g7", reason="out of area: Austin, TX"),
        rec(now - 30 * HOUR, "gopro", NOTIFIED, listing_id="g8", rating=5),
        # ipad: rejected, then notified when it was evaluated again (the record is replaced)
        rec(now - 10 * HOUR, "ipad", REJECTED, listing_id="i1", rating=2, ai_comment="Too old."),
        rec(
            now - 9 * HOUR,
            "ipad",
            NOTIFIED,
            listing_id="i1",
            rating=4,
            ai_comment="Price dropped.",
        ),
        rec(now - 8 * HOUR, "ipad", EXCLUDED, listing_id="i2", reason="banned seller: Bob"),
        # bike: only an exclusion more than 24 hours ago
        rec(now - 25 * HOUR, "bike", EXCLUDED, listing_id="b1", reason="out of area: Dallas, TX"),
    ]
    for record in saved:
        record_evaluation(record, local_cache=temp_cache)
    counter.increment(CounterItem.SEARCH_PERFORMED, "gopro", 12, local_cache=temp_cache)
    # counted for each listing a search returns, repeats included: not in the digest
    counter.increment(CounterItem.LISTING_EXAMINED, "gopro", 960, local_cache=temp_cache)
    counter.increment(CounterItem.SEARCH_PERFORMED, "ipad", 6, local_cache=temp_cache)
    # searches more than 24 hours ago are not counted
    stale = (
        CacheType.COUNTERS_DAILY.value,
        counter_minute(now - 30 * HOUR),
        CounterItem.SEARCH_PERFORMED.value,
        "bike",
    )
    temp_cache.set(stale, 99)

    digest = dg.compose_digest(until=now, local_cache=temp_cache)
    assert [item.name for item in digest.items] == ["gopro", "ipad"]
    gopro, ipad = digest.items
    assert (gopro.searches, gopro.evaluated) == (12, 7)
    assert [x.title for x in gopro.notified] == ["GoPro Hero 11", "GoPro 10"]
    assert gopro.notified[1].price == "$180 (was $250)"  # a price drop
    assert [x.rating for x in gopro.rejected] == [2, 1]
    assert gopro.rejected[0].comment == "Only the case is for sale."
    assert gopro.excluded == {"excluded keyword": 2, "out of area": 1}
    assert (ipad.searches, ipad.evaluated) == (6, 2)
    assert [x.comment for x in ipad.notified] == ["Price dropped."]
    assert ipad.rejected == [] and ipad.excluded == {"banned seller": 1}
    total = digest.total
    assert (total.searches, total.evaluated, len(total.notified), len(total.rejected)) == (
        18,
        9,
        3,
        2,
    )
    assert total.n_excluded == 4

    phone = dg.render_phone_digest(digest)
    assert phone.startswith(
        "Last 24 h: 18 searches, 9 listings evaluated, 3 notified, 2 rejected by AI, "
        "4 excluded\nTop matches (3)\n- [5] GoPro Hero 11, $200\n"
    )
    text, html = dg.render_email_digest(digest)
    assert "excluded keyword 2, out of area 1" in text
    assert "By item" in html and html.count("<h2") == 4  # digest, by item, gopro, ipad

    # records older than evaluation_history_days are ignored (and removed)
    set_history_days(5 * HOUR / (24 * HOUR))
    try:
        digest = dg.compose_digest(until=now, local_cache=temp_cache)
    finally:
        set_history_days(None)
    assert len(digest.total.notified) == 2  # g1 and g2; i1 is 9 hours old
    assert [x.name for x in digest.items] == ["gopro", "ipad"]  # ipad still has searches
    assert digest.items[1].notified == [] and digest.items[1].excluded == {}
    assert len(list(iter_evaluations(local_cache=temp_cache))) == 4


def test_user_digest_options() -> None:
    config = UserConfig(name="me", digest_at="8:05", digest_with="gmail")  # type: ignore[arg-type]
    assert (config.digest_at, config.digest_with) == ("08:05", ["gmail"])
    assert UserConfig(name="me", digest_at=False).digest_at is None  # type: ignore[arg-type]
    for bad in ("25:00", "8am", "08:60", 8):
        with pytest.raises(ValueError, match="digest_at"):
            UserConfig(name="me", digest_at=bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="digest_with"):
        UserConfig(name="me", digest_with=[1])  # type: ignore[list-item]


CONFIG = """
[marketplace.facebook]
search_city = "houston"

[item.gopro]
search_phrases = "gopro"

[notification.gmail]
smtp_server = "smtp.gmail.com"
smtp_username = "me@gmail.com"
smtp_password = "pw"

[notification.unitysvc_email]
smtp_password = "svcpass_abc"

[notification.tg]
telegram_token = "123:abc"

[notification.off]
ntfy_server = "https://ntfy.sh"
enabled = false

[user.me]
email = "me@example.com"
telegram_chat_id = "456"
digest_at = "08:00"
max_retries = 1
retry_delay = 0
"""


def load(config_file: Callable[[str], str], extra: str = "") -> Config:
    return Config([Path(config_file(CONFIG + extra))])


def test_digest_with_is_validated(config_file: Callable[[str], str]) -> None:
    assert load(config_file, 'digest_with = ["gmail", "tg"]').user["me"].digest_with == [
        "gmail",
        "tg",
    ]
    for names in ('"nope"', '"off"'):
        with pytest.raises(ValueError, match="digest_with"):
            load(config_file, f"digest_with = {names}")
    # only notifications the user receives
    with pytest.raises(ValueError, match="digest_with"):
        load(config_file, 'notify_with = ["tg"]\ndigest_with = ["gmail"]')


def test_digest_channels(config_file: Callable[[str], str]) -> None:
    # by default, every channel the user is notified with
    config = load(config_file)
    assert sorted(dg.digest_channels(config.user["me"], config.notification)) == [
        "email",
        "telegram",
    ]
    # one of two email sections
    config = load(config_file, 'digest_with = ["gmail"]')
    channels = dg.digest_channels(config.user["me"], config.notification)
    assert list(channels) == ["gmail"]
    gmail = channels["gmail"]
    assert isinstance(gmail, EmailNotificationConfig)
    assert (gmail.smtp_server, gmail.email) == ("smtp.gmail.com", ["me@example.com"])
    config = load(config_file, 'digest_with = ["unitysvc_email", "tg"]')
    channels = dg.digest_channels(config.user["me"], config.notification)
    assert list(channels) == ["unitysvc_email", "tg"]
    unitysvc_email = channels["unitysvc_email"]
    assert isinstance(unitysvc_email, EmailNotificationConfig)
    assert unitysvc_email.smtp_password == "svcpass_abc"


#
# sending, with fake channels
#
Sent = List[Tuple[str, str, str]]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Sent:
    """Record the messages instead of sending them."""
    messages: Sent = []

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
        digest_at="08:00",
        pushover_user_key="u",
        pushover_api_token="t",
        telegram_token="123:abc",
        telegram_chat_id="456",
        max_retries=1,
        retry_delay=0,
        **kwargs,
    )


def test_send_digest_version_by_channel_type(sent: Sent) -> None:
    digest = dg.compose_digest(SINCE, NOW)
    config = user(email=["me@example.com"], smtp_password="p")
    assert dg.send_digest(config, digest) == {"email": True, "pushover": True, "telegram": True}
    by_channel = {channel: (title, message) for channel, title, message in sent}
    assert all(title == digest.title for title, _ in by_channel.values())
    # the full digest by email, the phone digest on push channels
    assert "<html>" in by_channel["email"][1] and "Rejected by AI" in by_channel["email"][1]
    assert by_channel["pushover"][1] == dg.render_phone_digest(digest, "html")
    # Telegram escapes Markdown, so it gets plain text
    assert by_channel["telegram"][1] == dg.render_phone_digest(digest, "plain_text")


Window = Tuple[float, float]


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> List[Window]:
    """The (since, until) of each digest composed for sending."""
    composed: List[Window] = []
    compose = dg.compose_digest

    def record(since: float, until: float, local_cache: Cache | None = None) -> dg.Digest:
        composed.append((since, until))
        return compose(since, until, local_cache=local_cache)

    monkeypatch.setattr(dg, "compose_digest", record)
    return composed


DAY1 = datetime(2026, 10, 8, 8, 0)
CUTOFF1 = DAY1.timestamp()
CUTOFF2 = (DAY1 + timedelta(days=1)).timestamp()
CUTOFF0 = (DAY1 - timedelta(days=1)).timestamp()


def test_send_due_digest_once(sent: Sent, windows: List[Window], temp_cache: Cache) -> None:
    config = user()
    # due at 08:00: both channels get the 24 hours up to 08:00
    assert dg.send_due_digest(config, now=DAY1, local_cache=temp_cache)
    assert sorted(channel for channel, _, _ in sent) == ["pushover", "telegram"]
    assert windows == [(CUTOFF0, CUTOFF1)]
    assert temp_cache.get(dg.digest_key("me", "pushover")) == CUTOFF1
    # a restart or a config change runs the job again: not sent again
    for later in (DAY1.replace(hour=11), DAY1 + timedelta(hours=23, minutes=59)):
        assert not dg.send_due_digest(config, now=later, local_cache=temp_cache)
    assert len(sent) == 2
    # missed while aimm was down the next morning: sent once on the next start, with the
    # window of that day's digest
    next_day = DAY1 + timedelta(days=1, hours=5)
    assert dg.send_due_digest(config, now=next_day, local_cache=temp_cache)
    assert not dg.send_due_digest(config, now=next_day, local_cache=temp_cache)
    assert len(sent) == 4
    assert windows == [(CUTOFF0, CUTOFF1), (CUTOFF1, CUTOFF2)]


def test_send_due_digest_with_sections(
    sent: Sent, temp_cache: Cache, config_file: Callable[[str], str]
) -> None:
    config = load(config_file, 'digest_with = ["tg"]')
    now = datetime(2026, 10, 8, 9)
    assert dg.send_due_digest(
        config.user["me"], config.notification, now=now, local_cache=temp_cache
    )
    assert [channel for channel, _, _ in sent] == ["telegram"]


def fail_telegram(monkeypatch: pytest.MonkeyPatch, failing: bool) -> None:
    telegram = dg.channel_classes()["telegram"]
    if failing:

        def fail(*args: Any, **kwargs: Any) -> bool:
            raise RuntimeError("Telegram is down")

        monkeypatch.setattr(telegram, "send_message", fail)
    else:
        monkeypatch.setattr(
            telegram, "send_message", dg.channel_classes()["pushover"].send_message
        )


def test_failed_channel_is_retried_alone(
    monkeypatch: pytest.MonkeyPatch, sent: Sent, windows: List[Window], temp_cache: Cache
) -> None:
    config = user()
    now = DAY1.replace(hour=9)
    # Pushover succeeds, Telegram fails: only Pushover has today's digest
    fail_telegram(monkeypatch, True)
    assert dg.send_due_digest(config, now=now, local_cache=temp_cache)
    assert [channel for channel, _, _ in sent] == ["pushover"]
    assert temp_cache.get(dg.digest_key("me", "telegram")) is None
    assert dg.pending_digest_channels(config, now=now, local_cache=temp_cache) == ["telegram"]
    # retried later the same day: only Telegram, with the same window (not up to now)
    fail_telegram(monkeypatch, False)
    later = now + timedelta(hours=3)
    assert dg.send_due_digest(config, now=later, local_cache=temp_cache)
    assert [channel for channel, _, _ in sent] == ["pushover", "telegram"]
    assert windows == [(CUTOFF0, CUTOFF1), (CUTOFF0, CUTOFF1)]
    # all channels have it: nothing is sent again
    assert not dg.send_due_digest(config, now=later, local_cache=temp_cache)
    assert len(sent) == 2


def test_channel_behind_gets_one_catch_up_digest(
    monkeypatch: pytest.MonkeyPatch, sent: Sent, windows: List[Window], temp_cache: Cache
) -> None:
    config = user()
    # both channels received the digest of the day before
    assert dg.send_due_digest(config, now=DAY1 - timedelta(days=1), local_cache=temp_cache)
    fail_telegram(monkeypatch, True)
    assert dg.send_due_digest(config, now=DAY1, local_cache=temp_cache)
    fail_telegram(monkeypatch, False)
    # retried only after the next day's digest time: Pushover gets the new day, Telegram one
    # digest covering both days
    next_day = DAY1 + timedelta(days=1, hours=1)
    assert dg.send_due_digest(config, now=next_day, local_cache=temp_cache)
    assert windows[2:] == [(CUTOFF1, CUTOFF2), (CUTOFF0, CUTOFF2)]
    messages = {channel: message for channel, _, message in sent[3:]}
    assert messages["pushover"].startswith("Last 24 h: ")
    since = datetime.fromtimestamp(CUTOFF0)
    assert messages["telegram"].startswith(f"Since {since:%a %b} {since.day} 08:00: ")
    assert not dg.send_due_digest(config, now=next_day, local_cache=temp_cache)
    assert len(sent) == 5


def test_digest_after_an_outage_covers_at_most_7_days(
    sent: Sent, windows: List[Window], temp_cache: Cache
) -> None:
    config = user()
    assert dg.send_due_digest(config, now=DAY1, local_cache=temp_cache)
    # aimm was down for 10 days: one digest per channel, of the last 7 days
    back = DAY1 + timedelta(days=10, hours=2)
    assert dg.send_due_digest(config, now=back, local_cache=temp_cache)
    cutoff = (DAY1 + timedelta(days=10)).timestamp()
    assert windows[1:] == [(cutoff - dg.MAX_CATCH_UP, cutoff)]
    assert len(sent) == 4
    text, html = dg.render_email_digest(dg.compose_digest(cutoff - dg.MAX_CATCH_UP, cutoff))
    assert text.startswith("Listings evaluated since ") and "No matches since " in text
    assert "Listings evaluated since " in html
    assert not dg.send_due_digest(config, now=back, local_cache=temp_cache)
    assert len(sent) == 4


def test_failed_digest_is_retried(
    monkeypatch: pytest.MonkeyPatch, sent: Sent, temp_cache: Cache
) -> None:
    monkeypatch.setattr(
        dg, "send_digest", lambda *args, **kwargs: {"pushover": False, "telegram": False}
    )
    now = datetime(2026, 10, 8, 9)
    assert not dg.send_due_digest(user(), now=now, local_cache=temp_cache)
    assert sorted(dg.pending_digest_channels(user(), now=now, local_cache=temp_cache)) == [
        "pushover",
        "telegram",
    ]


def test_no_digest_without_option(sent: Sent, temp_cache: Cache) -> None:
    config = user()
    config.digest_at = None
    assert not dg.send_due_digest(config, now=datetime(2026, 10, 8, 9), local_cache=temp_cache)
    config.digest_at, config.enabled = "08:00", False
    assert not dg.send_due_digest(config, now=datetime(2026, 10, 8, 9), local_cache=temp_cache)
    assert sent == []


def test_schedule_digests_follow_config_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[str] = []
    monkeypatch.setattr(
        "ai_marketplace_monitor.monitor.send_due_digest",
        lambda config, notifications, logger=None: calls.append(config.name),
    )
    users = {"me": user(), "other": UserConfig(name="other")}
    monitor = MarketplaceMonitor.__new__(MarketplaceMonitor)
    monitor.logger = None
    monitor.config = types.SimpleNamespace(user=users, notification={})  # type: ignore[assignment]
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
        users["me"].digest_at = "20:30"
        monitor.schedule_digests()
        jobs = schedule.get_jobs()
        assert len(jobs) == 1 and jobs[0].at_time is not None
        assert jobs[0].at_time.strftime("%H:%M") == "20:30"
    finally:
        schedule.clear()
