"""AI-written summaries of each item in the daily digest.

For every item, the digest asks an AI service for one to three sentences: which listings look
promising, which sold, went pending or dropped in price, and the best bet. An item with nothing
new in the window gets a fixed sentence instead, without an AI call. Summaries are cached per
item and digest window, so every user and channel of the same digest shares one AI call.
"""

from contextlib import suppress
from logging import Logger
from typing import Any, Callable, List, Mapping, Tuple

from diskcache import Cache  # type: ignore

from .digest import DIGEST_PERIOD, MAX_CATCH_UP, Digest, DigestListing, ItemDigest, _count
from .utils import CacheType, cache, hilight

SUMMARY_MAX_WORDS = 60
SUMMARY_MAX_CHARS = 400
# rejected listings shown to the AI, best ratings first
PROMPT_REJECTED = 3

# (item name, prompt) -> the summary, or None if no AI service could write one
Summarizer = Callable[[str, str], "str | None"]


def nothing_new(item: ItemDigest, digest: Digest) -> str | None:
    """The fixed summary of an item with no evaluations and no updates, else None."""
    if item.evaluated or item.updates:
        return None
    return f"Nothing new {digest.window} ({_count(item.searches, 'search')})."


def _line(listing: DigestListing, with_comment: bool = True) -> str:
    rating = f"[rating {listing.rating}] " if listing.rating is not None else ""
    parts = [f"{rating}{listing.title}"]
    if listing.price:
        parts.append(listing.price)
    if listing.state:
        parts.append(listing.state)
    comment = f": {listing.comment}" if with_comment and listing.comment else ""
    return "- " + ", ".join(parts) + comment


def summary_prompt(item: ItemDigest, digest: Digest, item_config: Any | None = None) -> str:
    """What the AI is told about an item's day."""
    lines: List[str] = [f"Item: {item.name}"]
    if item_config is not None:
        phrases = ", ".join(getattr(item_config, "search_phrases", None) or [])
        if phrases:
            lines.append(f"Searching for: {phrases}")
        if getattr(item_config, "description", None):
            lines.append(f"Looking for: {item_config.description}")
        low = getattr(item_config, "min_price", None)
        high = getattr(item_config, "max_price", None)
        if low or high:
            lines.append(f"Price range: {low or 'any'} to {high or 'any'}")
    lines.append(
        f"Activity {digest.window}: {_count(item.searches, 'search')}, "
        f"{item.evaluated:,} listings evaluated, {len(item.notified):,} matches notified, "
        f"{len(item.rejected):,} rejected by the AI rating, {item.n_excluded:,} excluded"
    )
    if item.notified:
        lines.append("New matches (rating 1-5, price, status, AI comment):")
        lines.extend(_line(x) for x in item.notified)
    if item.updates:
        lines.append("Earlier matches that sold, went pending or changed price:")
        lines.extend(_line(x, with_comment=False) for x in item.updates)
    if item.rejected:
        lines.append("Best listings rejected by the AI rating:")
        lines.extend(_line(x) for x in item.rejected[:PROMPT_REJECTED])
    lines.append(
        f"Write 1 to 3 sentences, at most {SUMMARY_MAX_WORDS} words, plain text: which "
        "listings look promising, which sold, went pending or dropped in price, and the best "
        "bet if there is one. If nothing stands out, say so briefly."
    )
    return "\n".join(lines)


def summary_key(item_name: str, until: float) -> Tuple[str, str, str, float]:
    """Cache key of an item's summary for the digest window ending at ``until``."""
    return (CacheType.DIGEST.value, "summary", item_name, until)


def _clean(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    return text[: SUMMARY_MAX_CHARS - 1].rstrip() + "…"


def add_summaries(
    digest: Digest,
    summarize: Summarizer,
    item_configs: Mapping[str, Any] | None = None,
    logger: Logger | None = None,
    local_cache: Cache | None = None,
) -> None:
    """Set ``summary`` of each item of the digest; an item the AI cannot summarize has none."""
    c = cache if local_cache is None else local_cache
    failed: List[str] = []
    for item in digest.items:
        fixed = nothing_new(item, digest)
        if fixed is not None:
            item.summary = fixed
            continue
        key = summary_key(item.name, digest.until)
        try:
            cached = c.get(key)
        except Exception:
            cached = None
        if isinstance(cached, str) and cached:
            item.summary = cached
            continue
        config = (item_configs or {}).get(item.name)
        try:
            answer = summarize(item.name, summary_prompt(item, digest, config))
        except KeyboardInterrupt:
            raise
        except Exception:
            answer = None
        if not answer or not answer.strip():
            failed.append(item.name)
            continue
        item.summary = _clean(answer)
        with suppress(Exception):
            c.set(
                key, item.summary, expire=MAX_CATCH_UP + DIGEST_PERIOD, tag=CacheType.DIGEST.value
            )
    if failed and logger:
        logger.warning(
            f"""{hilight("[Digest]", "fail")} No AI summary for {", ".join(failed)}; the digest is sent without it."""
        )
