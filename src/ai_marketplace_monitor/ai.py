import base64
import contextlib
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from logging import Logger
from typing import Any, Callable, ClassVar, Dict, Generic, List, Optional, Tuple, Type, TypeVar

import requests  # type: ignore
from diskcache import Cache  # type: ignore
from PIL import Image

from .listing import Listing
from .marketplaces.base import TItemConfig, TMarketplaceConfig, resolve_option
from .utils import BaseConfig, CacheType, CounterItem, cache, counter, hilight


class AIServiceProvider(Enum):
    OPENAI = "OpenAI"
    DEEPSEEK = "DeepSeek"
    GEMINI = "Gemini"
    ANTHROPIC = "Anthropic"
    OLLAMA = "Ollama"
    UNITYSVC = "UnitySVC"
    SUBSCRIPTION = "subscription"


def _answer_key(listing: Listing, item_config: Any, marketplace_config: Any) -> Tuple[Any, ...]:
    """The cache key of an AI answer.

    It includes how much was known about the seller, so that an answer given before the
    seller's profile could be read is not reused once it has been; later changes to a profile
    keep the answer.
    """
    key: Tuple[Any, ...] = (
        CacheType.AI_INQUIRY.value,
        item_config.hash,
        marketplace_config.hash,
        listing.hash,
    )
    return (*key, listing.seller_state) if listing.seller_state else key


@dataclass
class AIResponse:
    score: int
    comment: str
    name: str = ""

    NOT_EVALUATED: ClassVar = "Not evaluated by AI"

    @property
    def conclusion(self: "AIResponse") -> str:
        return {
            1: "No match",
            2: "Potential match",
            3: "Poor match",
            4: "Good match",
            5: "Great deal",
        }[self.score]

    @property
    def style(self: "AIResponse") -> str:
        if self.comment == self.NOT_EVALUATED:
            return "dim"
        if self.score < 3:
            return "fail"
        if self.score > 3:
            return "succ"
        return "name"

    @property
    def stars(self: "AIResponse") -> str:
        full_stars = self.score
        empty_stars = 5 - full_stars
        return (
            '<span style="color: #FFD700; font-size: 20px;">★</span>' * full_stars
            + '<span style="color: #D3D3D3; font-size: 20px;">☆</span>' * empty_stars
        )

    @classmethod
    def from_cache(
        cls: Type["AIResponse"],
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
        local_cache: Cache | None = None,
    ) -> Optional["AIResponse"]:
        res = (cache if local_cache is None else local_cache).get(
            _answer_key(listing, item_config, marketplace_config)
        )
        if res is None:
            return None
        return AIResponse(**res)

    @classmethod
    def forget(
        cls: Type["AIResponse"],
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
        local_cache: Cache | None = None,
    ) -> None:
        """Drop the cached answer, so that the AI is asked again."""
        (cache if local_cache is None else local_cache).delete(
            _answer_key(listing, item_config, marketplace_config)
        )

    def to_cache(
        self: "AIResponse",
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
        local_cache: Cache | None = None,
    ) -> None:
        (cache if local_cache is None else local_cache).set(
            _answer_key(listing, item_config, marketplace_config),
            asdict(self),
            tag=CacheType.AI_INQUIRY.value,
        )


# seconds in each unit of rate_limit, e.g. "15/minute"
RATE_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
RATE_UNIT_ALIASES = {"s": "second", "sec": "second", "min": "minute", "h": "hour", "hr": "hour"}
# the longest wait for a rate-limited request before aimm gives up on the AI
MAX_RETRY_AFTER = 300


def rate_limit_interval(rate_limit: str) -> float:
    """Seconds between requests for a rate such as ``"15/minute"`` or ``"1000/hour"``."""
    matched = re.fullmatch(r"\s*(\d+(?:\.\d*)?)\s*/\s*([a-z]+?)s?\s*", rate_limit.lower())
    if matched is None:
        raise ValueError(f"Invalid rate_limit {rate_limit!r}")
    count, unit = float(matched.group(1)), matched.group(2)
    unit = RATE_UNIT_ALIASES.get(unit, unit)
    if unit not in RATE_UNITS or count <= 0:
        raise ValueError(f"Invalid rate_limit {rate_limit!r}")
    return RATE_UNITS[unit] / count


def retry_after(error: Exception) -> float | None:
    """Seconds a rate-limited (HTTP 429) request asks to wait, or None for other errors."""
    if getattr(error, "status_code", None) != 429:
        return None
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    # OpenAI also sends milliseconds
    if headers.get("retry-after-ms") is not None:
        try:
            return float(headers["retry-after-ms"]) / 1000
        except ValueError:
            pass
    value = headers.get("retry-after")
    if value is not None:
        try:
            return float(value)
        except ValueError:
            pass
        # retry-after may also be an HTTP date
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            delay = 0
        if delay > 0:
            return delay
    return 5


@dataclass
class AIConfig(BaseConfig):
    # this argument is required

    api_key: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    max_retries: int = 10
    timeout: int | None = None
    use_images: bool = True
    image_detail: str = "low"
    # the most requests the service accepts, e.g. "15/minute"; sent evenly spaced
    rate_limit: str | None = None

    def handle_provider(self: "AIConfig") -> None:
        if self.provider is None:
            return
        if self.provider.lower() not in [x.value.lower() for x in AIServiceProvider]:
            raise ValueError(
                f"""AIConfig requires a valid service provider. Valid providers are {hilight(", ".join([x.value for x in AIServiceProvider]))}"""
            )

    def handle_api_key(self: "AIConfig") -> None:
        if self.api_key is None:
            return
        if not isinstance(self.api_key, str):
            raise ValueError("AIConfig requires a string api_key.")
        self.api_key = self.api_key.strip()

    def handle_max_retries(self: "AIConfig") -> None:
        if not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ValueError("AIConfig requires a positive integer max_retries.")

    def handle_timeout(self: "AIConfig") -> None:
        if self.timeout is None:
            return
        if not isinstance(self.timeout, int) or self.timeout < 0:
            raise ValueError("AIConfig requires a positive integer timeout.")

    def handle_rate_limit(self: "AIConfig") -> None:
        if self.rate_limit is None:
            return
        try:
            if not isinstance(self.rate_limit, str):
                raise ValueError
            rate_limit_interval(self.rate_limit)
        except ValueError:
            raise ValueError(
                f"AIConfig rate_limit {self.rate_limit!r} should be a number of requests per "
                'second, minute, hour or day, such as "15/minute", "1000/hour" or "1500/day".'
            ) from None

    def handle_use_images(self: "AIConfig") -> None:
        if not isinstance(self.use_images, bool):
            raise ValueError("AIConfig requires a boolean use_images.")

    def handle_image_detail(self: "AIConfig") -> None:
        if self.image_detail not in {"low", "high", "original", "auto"}:
            raise ValueError("AIConfig image_detail must be low, high, original, or auto.")


@dataclass
class OpenAIConfig(AIConfig):
    def handle_api_key(self: "OpenAIConfig") -> None:
        if self.enabled is False and self.api_key is None:
            return
        if self.api_key is None:
            raise ValueError("OpenAI requires a string api_key.")


@dataclass
class DeekSeekConfig(OpenAIConfig):
    pass


@dataclass
class GeminiConfig(OpenAIConfig):
    pass


@dataclass
class OllamaConfig(OpenAIConfig):
    api_key: str | None = field(default="ollama")  # required but not used.

    def handle_base_url(self: "OllamaConfig") -> None:
        if self.base_url is None:
            raise ValueError("Ollama requires a string base_url.")

    def handle_model(self: "OllamaConfig") -> None:
        if self.model is None:
            raise ValueError("Ollama requires a string model.")


@dataclass
class UnitySVCConfig(OpenAIConfig):
    def handle_api_key(self: "UnitySVCConfig") -> None:
        if self.api_key is None:
            raise ValueError(
                'UnitySVC requires a string api_key, e.g. api_key = "${UNITYSVC_API_KEY}".'
            )


@dataclass
class AnthropicConfig(AIConfig):
    def handle_api_key(self: "AnthropicConfig") -> None:
        if self.api_key is None:
            raise ValueError("Anthropic requires a string api_key.")


# credentials and providers that would bill an API account instead of the subscription
BILLING_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "CODEX_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI",
)
# options of agent CLIs that let the model act without asking (run commands, edit files)
UNSAFE_OPTIONS = (
    "--dangerously-skip-permissions",  # claude
    "--allow-dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",  # codex
    "--full-auto",
    "--yolo",  # gemini
    "-y",
)
# options of claude that aimm sets itself, or that give it tools, servers, settings or files
CLAUDE_RESERVED = (
    "--tools",
    "--allowedTools",
    "--allowed-tools",
    "--disallowedTools",
    "--disallowed-tools",
    "--permission-mode",
    "--mcp-config",
    "--strict-mcp-config",
    "--settings",
    "--setting-sources",
    "--add-dir",
    "--plugin-dir",
    "--agents",
    "--input-format",
    "--output-format",
    "--system-prompt",
    "--append-system-prompt",
    "--resume",
    "--continue",
    "-c",
    "-r",
)


@dataclass
class SubscriptionConfig(AIConfig):
    # the command of a CLI signed in with a subscription, e.g. "claude -p --model sonnet"
    command: str | List[str] | None = None
    # run a command aimm has no safety profile for (anything but claude)
    allow_any_command: bool = False
    # variables of BILLING_ENV to pass to the command anyway
    keep_env: List[str] = field(default_factory=list)

    def handle_api_key(self: "SubscriptionConfig") -> None:
        if self.api_key is not None:
            raise ValueError(
                "A subscription section uses the login of its command, not an api_key; "
                "remove api_key from the section."
            )

    def handle_command(self: "SubscriptionConfig") -> None:
        if self.enabled is False and self.command is None:
            return
        argv = command_argv(self.command)
        if not argv:
            raise ValueError(
                'A subscription section needs a command, e.g. command = "claude -p --model sonnet".'
            )
        unsafe = [arg for arg in argv if arg.split("=", 1)[0] in UNSAFE_OPTIONS]
        unsafe += [a for a in argv if a.startswith("--approval-mode") and "default" not in a]
        if unsafe:
            raise ValueError(
                f"The command of [ai.{self.name}] has {', '.join(unsafe)}, which lets the AI act "
                "without asking. Listings are written by strangers: remove it."
            )
        if is_claude(argv):
            reserved = [a for a in argv[1:] if a.split("=", 1)[0] in CLAUDE_RESERVED]
            if reserved:
                raise ValueError(
                    f"The command of [ai.{self.name}] sets {', '.join(reserved)}; aimm runs claude "
                    "without tools, servers or settings and chooses these options itself. "
                    "Remove them."
                )
        elif not self.allow_any_command:
            raise ValueError(
                f"aimm knows how to run claude safely, but not {argv[0]}. Listings are written by "
                "strangers, and an AI that can use tools could be told to by one. If "
                f"{argv[0]} cannot run commands or change files in this mode, set "
                "allow_any_command = true."
            )

    def handle_keep_env(self: "SubscriptionConfig") -> None:
        if not isinstance(self.keep_env, list) or not all(
            isinstance(v, str) for v in self.keep_env
        ):
            raise ValueError("keep_env must be a list of environment variable names.")


def command_argv(command: Any) -> List[str]:
    """The arguments of a command given as a string (split like a shell) or a list."""
    if isinstance(command, str):
        return shlex.split(command)
    if isinstance(command, list) and all(isinstance(a, str) for a in command):
        return list(command)
    return []


def is_claude(argv: List[str]) -> bool:
    return bool(argv) and os.path.basename(argv[0]) == "claude"


TAIConfig = TypeVar("TAIConfig", bound=AIConfig)

# told to the AI along with the photo, so it checks what is actually for sale
IMAGE_NOTE = (
    "The listing's main photo is attached. Use it to check what is actually being sold "
    "(for example a case, cover or accessory instead of the device) and its visible condition."
)


@dataclass
class ListingImage:
    """A listing photo downloaded by aimm, ready to embed in an AI request."""

    media_type: str
    data: str  # base64

    @property
    def data_url(self: "ListingImage") -> str:
        return f"data:{self.media_type};base64,{self.data}"


# longest side of a photo sent to the AI; enough to tell what is for sale, and few tokens
IMAGE_MAX_SIDE = 800

# the daily digest asks the AI for a short summary of each item; a few quick tries are enough,
# because a missing summary only leaves it out of the digest
SUMMARY_SYSTEM = (
    "You summarize a day of marketplace searches for the person who set them up. "
    "Be brief, concrete and plain: no markdown, no links, no greetings."
)
SUMMARY_RETRIES = 2
# seconds a single summary request may take, so that an AI outage cannot hold up the digest
SUMMARY_TIMEOUT = 60


def fetch_listing_image(
    url: str, max_side: int = IMAGE_MAX_SIDE, timeout: int = 15
) -> ListingImage:
    """Download a listing photo and shrink it so its longest side is at most ``max_side``.

    The photo is sent to the AI as data rather than as its URL: Facebook photo URLs expire,
    and not every AI service fetches image URLs.
    """
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    with Image.open(io.BytesIO(response.content)) as img:
        img.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=85)
    return ListingImage("image/jpeg", base64.b64encode(buffer.getvalue()).decode("ascii"))


def token_usage(response: Any) -> str:
    """Summarize the token usage of an OpenAI or Anthropic response, if reported."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return ""
    # OpenAI-compatible APIs use prompt/completion, Anthropic uses input/output
    sent = getattr(usage, "prompt_tokens", None)
    if sent is None:
        sent = getattr(usage, "input_tokens", None)
    received = getattr(usage, "completion_tokens", None)
    if received is None:
        received = getattr(usage, "output_tokens", None)
    if not isinstance(sent, int) or not isinstance(received, int):
        return ""
    return f" ({sent} input / {received} output tokens)"


def rating_and_comment(answer: str) -> Tuple[int, str]:
    """The rating and the summary from an AI answer that contains "Rating <1-5>: <summary>"."""
    lines = answer.split("\n")
    # if any of the lines contains "Rating: ", extract the rating from it.
    score: int = 1
    comment = ""
    rating_line = None
    for idx, line in enumerate(lines):
        matched = re.match(r".*Rating[^1-5]*([1-5])[:\s]*(.*)", line)
        if matched:
            score = int(matched.group(1))
            comment = matched.group(2).strip()
            rating_line = idx
            continue
        if rating_line is not None:
            # if the AI puts comment after Rating, we need to include them
            comment += " " + line
    # if the AI puts the rating at the end, let us try to use the line before the Rating line
    if len(comment.strip()) < 5 and rating_line is not None and rating_line > 0:
        comment = lines[rating_line - 1]

    # remove multiple spaces
    return score, " ".join([x for x in comment.split() if x.strip()]).strip()


class AIBackend(Generic[TAIConfig]):
    # longest side of the listing photo this backend sends
    image_max_side: ClassVar[int] = IMAGE_MAX_SIDE

    def __init__(self: "AIBackend", config: AIConfig, logger: Logger | None = None) -> None:
        self.config = config
        self.logger = logger
        self.client: Any = None
        # time.monotonic() when the last request was sent, for rate_limit
        self.last_request: float | None = None

    @property
    def min_interval(self: "AIBackend") -> float:
        """Seconds to wait between two requests, from rate_limit; 0 if there is none."""
        if not self.config.rate_limit:
            return 0
        return rate_limit_interval(self.config.rate_limit)

    def wait_for_rate_limit(self: "AIBackend") -> None:
        """Wait until min_interval has passed since the last request, then count this one.

        Called right before each request to the service, retries included.
        """
        if self.last_request is not None and self.min_interval:
            wait = self.last_request + self.min_interval - time.monotonic()
            if wait > 0:
                if self.logger:
                    self.logger.debug(
                        f"""{hilight("[AI]", "info")} Waiting {wait:.1f} seconds for the rate_limit {self.config.rate_limit} of {self.config.name}."""
                    )
                time.sleep(wait)
        self.last_request = time.monotonic()

    def retry_delay(self: "AIBackend", error: Exception) -> float:
        """Seconds to wait before retrying a failed request.

        A rate-limited request waits as long as the service asks, unless that is more than
        MAX_RETRY_AFTER (for example a used-up daily quota): then aimm gives up on this AI.
        """
        delay = retry_after(error)
        if delay is None:
            return 5
        if delay > MAX_RETRY_AFTER:
            raise RuntimeError(
                f"{self.config.name} is rate limited for another {delay:.0f} seconds"
            ) from error
        return delay

    @classmethod
    def get_config(cls: Type["AIBackend"], **kwargs: Any) -> TAIConfig:
        raise NotImplementedError("get_config method must be implemented by subclasses.")

    def connect(self: "AIBackend") -> None:
        raise NotImplementedError("Connect method must be implemented by subclasses.")

    def summarize(self: "AIBackend", prompt: str) -> str:
        """A short free-form answer to ``prompt``, for the daily digest."""
        raise NotImplementedError("summarize must be implemented by subclasses.")

    def _summarize_with(self: "AIBackend", ask: Callable[[], str]) -> str:
        """Call ``ask`` up to SUMMARY_RETRIES times; its stripped, non-empty answer."""
        last_error: Exception | None = None
        delay: float = 5
        for attempt in range(SUMMARY_RETRIES):
            if attempt:
                time.sleep(delay)
            try:
                self.connect()
                self.wait_for_rate_limit()
                answer = (ask() or "").strip()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                last_error = e
                self.client = None
                delay = self.retry_delay(e)
                continue
            if not answer:
                raise RuntimeError(f"{self.config.name} gave an empty summary")
            return answer
        raise RuntimeError(
            f"{self.config.name} failed to summarize after {SUMMARY_RETRIES} tries"
        ) from last_error

    def listing_image(self: "AIBackend", listing: Listing) -> ListingImage | None:
        """The listing's main photo for the AI, or None if not wanted or not available."""
        if not self.config.use_images or not listing.image:
            return None
        try:
            return fetch_listing_image(listing.image, self.image_max_side)
        except Exception as e:
            if self.logger:
                self.logger.warning(
                    f"""{hilight("[AI-Error]", "fail")} Could not download the photo of {hilight(listing.title)}, evaluating its text only: {e}"""
                )
            return None

    def get_prompt(
        self: "AIBackend",
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
    ) -> str:
        prompt = (
            f"""A user wants to buy a {item_config.name} from Facebook Marketplace. """
            f"""Search phrases: "{'" and "'.join(item_config.search_phrases)}", """
        )
        if item_config.description:
            prompt += f"""Description: "{item_config.description}", """
        #
        max_price = (
            resolve_option("max_price", item_config, marketplace_config, site="ai_prompt") or 0
        )
        min_price = (
            resolve_option("min_price", item_config, marketplace_config, site="ai_prompt") or 0
        )
        if max_price and min_price:
            prompt += f"""Price range: {min_price} to {max_price}. """
        elif max_price:
            prompt += f"""Max price {max_price}. """
        elif min_price:
            prompt += f"""Min price {min_price}. """
        #
        if item_config.antikeywords:
            prompt += f"""Exclude keywords "{'" and "'.join(item_config.antikeywords)}" in title or description."""
        #
        prompt += (
            f"""\n\nThe user found a listing titled "{listing.title}" in {listing.condition} condition, """
            f"""priced at {listing.price}, located in {listing.location}, """
            f"""posted at {listing.post_url} with description "{listing.description}"\n\n"""
        )
        # bait prices: in every prompt, with or without seller information or a custom prompt
        prompt += (
            "Beware of bait prices: a price far below the item's market value together with "
            '"financing available", "payment plans", "no credit check", "rent to own", '
            '"layaway" or the like means that the listed price is a down payment or a monthly '
            "payment, not the price of the item. Rate such a listing 1, however well it "
            "matches. Financing or layaway at a realistic price is typical of a pawnshop or a "
            "dealer rather than a private seller: say so in your summary, and lower the rating "
            "if the user did not ask for a business.\n\n"
        )
        seller = listing.seller_info.get("summary") if listing.seller_info else ""
        warnings = listing.seller_info.get("warnings") if listing.seller_info else []
        if seller or warnings:
            prompt += (
                f"""About the seller, {listing.seller}: {seller or "nothing more is known"}.\n"""
            )
            if not (listing.seller_info.get("seller") or {}).get("profile_checked"):
                prompt += (
                    "The seller's profile could not be read, so their listings and sales are "
                    "unknown: treat the seller as not verified.\n"
                )
            if warnings:
                prompt += f"""Warning signs about the seller: {"; ".join(warnings)}.\n"""
            prompt += (
                "The seller matters as much as the item: a listing that matches perfectly is "
                "still a bad deal from a scammer, a dealer posing as a private seller, or "
                "someone who does not show up. Judge whether the seller is legitimate and "
                "reliable from everything known together, not from any one sign: many "
                "sellers never mark items as sold, a new account with many listings and none "
                "sold may be someone's moving sale, and a dealer with dozens of listings may "
                "be reputable, especially with good ratings. Be suspicious when the signs add "
                "up, for example a new or unrated account with many listings and no sales "
                "offering this item well below its market price, a single unusually cheap "
                "listing on a new account, a description that is vague or pushes for "
                "shipping, deposits or contact off Facebook, or reviews that mention "
                "no-shows, no responses or fraud. Rate a listing from a likely scammer no "
                "higher than 2, however well the item matches, and lower the rating for an "
                "unreliable or unverified seller. Always say in your summary what you "
                "concluded about the seller.\n\n"
            )
        # prompt
        custom_prompt = resolve_option("prompt", item_config, marketplace_config)
        if custom_prompt is not None:
            prompt += custom_prompt
        else:
            prompt += (
                "Evaluate how well this listing matches the user's criteria. Assess the description, MSRP, model year, "
                "condition, and seller's credibility."
            )
        # extra_prompt
        prompt += "\n"
        extra_prompt = resolve_option("extra_prompt", item_config, marketplace_config)
        if extra_prompt is not None:
            prompt += f"\n{extra_prompt.strip()}\n"
        # rating_prompt
        rating_prompt = resolve_option("rating_prompt", item_config, marketplace_config)
        if rating_prompt is not None:
            prompt += f"\n{rating_prompt.strip()}\n"
        else:
            prompt += (
                "\nRate from 1 to 5 based on the following: \n"
                "1 - No match: Missing key details, wrong category/brand, suspicious activity (e.g., external links), a bait price, or a likely scam seller.\n"
                "2 - Potential match: Lacks essential info (e.g., condition, brand, or model); needs clarification.\n"
                "3 - Poor match: Some mismatches or missing details; acceptable but not ideal.\n"
                "4 - Good match: Mostly meets criteria with clear, relevant details.\n"
                "5 - Great deal: Fully matches criteria, with excellent condition or price.\n"
                "Conclude with:\n"
                '"Rating <1-5>: <summary>"\n'
                "where <1-5> is the rating and <summary> is a brief recommendation (max 30 words)."
            )
        if self.logger:
            self.logger.debug(f"""{hilight("[AI-Prompt]", "info")} {prompt}""")
        return prompt

    def evaluate(
        self: "AIBackend",
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
    ) -> AIResponse:
        raise NotImplementedError("Confirm method must be implemented by subclasses.")


class OpenAIBackend(AIBackend):
    default_model = "gpt-4o"
    # the default is f"https://api.openai.com/v1"
    base_url: str | None = None

    @classmethod
    def get_config(cls: Type["OpenAIBackend"], **kwargs: Any) -> OpenAIConfig:
        return OpenAIConfig(**kwargs)

    def connect(self: "OpenAIBackend") -> None:
        if self.client is None:
            from openai import OpenAI  # type: ignore

            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url or self.base_url,
                timeout=self.config.timeout,
                # no SDK retries: every request goes through rate_limit and aimm's retries
                max_retries=0,
                default_headers={
                    "X-Title": "AI Marketplace Monitor",
                    "HTTP-Referer": "https://github.com/BoPeng/ai-marketplace-monitor",
                },
            )
            if self.logger:
                self.logger.info(f"""{hilight("[AI]", "name")} {self.config.name} connected.""")

    def summarize(self: "OpenAIBackend", prompt: str) -> str:
        def ask() -> str:
            # no SDK retries: SUMMARY_RETRIES is the whole budget
            response = self.client.with_options(max_retries=0).chat.completions.create(
                model=self.config.model or self.default_model,
                messages=[
                    {"role": "system", "content": SUMMARY_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                timeout=SUMMARY_TIMEOUT,
            )
            return response.choices[0].message.content or ""

        return self._summarize_with(ask)

    def evaluate(
        self: "OpenAIBackend",
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
    ) -> AIResponse:
        # ask openai to confirm the item is correct
        counter.increment(CounterItem.AI_QUERY, item_config.name)
        prompt = self.get_prompt(listing, item_config, marketplace_config)
        res: AIResponse | None = AIResponse.from_cache(listing, item_config, marketplace_config)
        if res is not None:
            if self.logger:
                self.logger.debug(
                    f"""{hilight("[AI]", res.style)} {self.config.name} previously concluded {hilight(f"{res.conclusion} ({res.score}): {res.comment}", res.style)} for listing {hilight(listing.title)}."""
                )
            return res

        self.connect()

        retries = 0
        response: Any | None = None
        last_error: Exception | None = None
        image = self.listing_image(listing)
        while retries < self.config.max_retries:
            self.connect()
            assert self.client is not None
            user_message = self._user_message(prompt, image)
            self.wait_for_rate_limit()
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model or self.default_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful assistant that can confirm if a user's search criteria matches the item he is interested in.",
                        },
                        user_message,
                    ],
                    stream=False,
                )
                break
            except KeyboardInterrupt:
                raise
            except Exception as e:
                last_error = e
                # a rate-limited request is retried as it was, after the wait below
                if image is not None and retry_after(e) is None:
                    # the model may not support images, so fall back to text-only
                    if self.logger:
                        self.logger.warning(
                            f"""{hilight("[AI-Error]", "fail")} {self.config.name} failed to evaluate {hilight(listing.title)} with image, retrying without image: {e}"""
                        )
                    image = None
                    continue
                if self.logger:
                    self.logger.error(
                        f"""{hilight("[AI-Error]", "fail")} {self.config.name} failed to evaluate {hilight(listing.title)}: {e}"""
                    )
                retries += 1
                delay = self.retry_delay(e)
                # try to initiate a connection
                self.client = None
                time.sleep(delay)

        if response is None:
            raise RuntimeError(
                f"{self.config.name} failed to evaluate {listing.title} after {retries} retries"
            ) from last_error

        answer = response.choices[0].message.content or ""
        # log the answer only: the full response object repeats every field
        # and includes the model's reasoning, flooding the logs
        if self.logger:
            self.logger.debug(
                f"""{hilight("[AI-Response]", "info")} {answer}{token_usage(response)}"""
            )
        if (
            answer is None
            or not answer.strip()
            or re.search(r"Rating[^1-5]*[1-5]", answer, re.DOTALL) is None
        ):
            counter.increment(CounterItem.FAILED_AI_QUERY, item_config.name)
            raise ValueError(f"Empty or invalid response from {self.config.name}: {response}")

        score, comment = rating_and_comment(answer)
        res = AIResponse(name=self.config.name, score=score, comment=comment)
        res.to_cache(listing, item_config, marketplace_config)
        counter.increment(CounterItem.NEW_AI_QUERY, item_config.name)
        return res

    def _user_message(
        self: "OpenAIBackend", prompt: str, image: ListingImage | None
    ) -> dict[str, Any]:
        if image is None:
            return {"role": "user", "content": prompt}
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": f"{prompt}\n{IMAGE_NOTE}"},
                {
                    "type": "image_url",
                    "image_url": {"url": image.data_url, "detail": self.config.image_detail},
                },
            ],
        }


class DeepSeekBackend(OpenAIBackend):
    default_model = "deepseek-chat"
    base_url = "https://api.deepseek.com"

    @classmethod
    def get_config(cls: Type["DeepSeekBackend"], **kwargs: Any) -> DeekSeekConfig:
        return DeekSeekConfig(**kwargs)


class GeminiBackend(OpenAIBackend):
    """Google Gemini via its OpenAI-compatible endpoint."""

    default_model = "gemini-2.5-flash"
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"

    @classmethod
    def get_config(cls: Type["GeminiBackend"], **kwargs: Any) -> GeminiConfig:
        return GeminiConfig(**kwargs)


class OllamaBackend(OpenAIBackend):
    default_model = "deepseek-r1:14b"

    @classmethod
    def get_config(cls: Type["OllamaBackend"], **kwargs: Any) -> OllamaConfig:
        return OllamaConfig(**kwargs)


class UnitySVCBackend(OpenAIBackend):
    """UnitySVC's `llm` platform service, reached through its OpenAI-compatible endpoint.

    `model` selects a capability tier, and UnitySVC picks the provider and fails over.
    """

    default_model = "balanced"
    base_url = "https://api.svcpass.com/p/llm"

    @classmethod
    def get_config(cls: Type["UnitySVCBackend"], **kwargs: Any) -> UnitySVCConfig:
        return UnitySVCConfig(**kwargs)


class AnthropicBackend(AIBackend):
    default_model = "claude-sonnet-5-5"
    # Anthropic charges about width x height / 750 tokens per image and has no `detail`
    # option, so a smaller photo keeps it near the cost of OpenAI's low detail
    image_max_side = 400

    @classmethod
    def get_config(cls: Type["AnthropicBackend"], **kwargs: Any) -> AnthropicConfig:
        return AnthropicConfig(**kwargs)

    def connect(self: "AnthropicBackend") -> None:
        if self.client is None:
            import anthropic  # type: ignore

            self.client = anthropic.Anthropic(
                api_key=self.config.api_key,
                timeout=self.config.timeout,
                # no SDK retries: every request goes through rate_limit and aimm's retries
                max_retries=0,
            )
            if self.logger:
                self.logger.info(f"""{hilight("[AI]", "name")} {self.config.name} connected.""")

    def summarize(self: "AnthropicBackend", prompt: str) -> str:
        def ask() -> str:
            # no SDK retries: SUMMARY_RETRIES is the whole budget
            response = self.client.with_options(max_retries=0).messages.create(
                model=self.config.model or self.default_model,
                max_tokens=300,
                system=SUMMARY_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                timeout=SUMMARY_TIMEOUT,
            )
            return response.content[0].text if response.content else ""

        return self._summarize_with(ask)

    def evaluate(
        self: "AnthropicBackend",
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
    ) -> AIResponse:
        counter.increment(CounterItem.AI_QUERY, item_config.name)
        prompt = self.get_prompt(listing, item_config, marketplace_config)
        res: AIResponse | None = AIResponse.from_cache(listing, item_config, marketplace_config)
        if res is not None:
            if self.logger:
                self.logger.debug(
                    f"""{hilight("[AI]", res.style)} {self.config.name} previously concluded {hilight(f"{res.conclusion} ({res.score}): {res.comment}", res.style)} for listing {hilight(listing.title)}."""
                )
            return res

        self.connect()

        retries = 0
        response: Any | None = None
        last_error: Exception | None = None
        image = self.listing_image(listing)
        while retries < self.config.max_retries:
            self.connect()
            assert self.client is not None
            self.wait_for_rate_limit()
            try:
                response = self.client.messages.create(
                    model=self.config.model or self.default_model,
                    max_tokens=1024,
                    system="You are a helpful assistant that can confirm if a user's search criteria matches the item he is interested in.",
                    messages=[self._user_message(prompt, image)],
                )
                break
            except KeyboardInterrupt:
                raise
            except Exception as e:
                last_error = e
                # a rate-limited request is retried as it was, after the wait below
                if image is not None and retry_after(e) is None:
                    # the model may not support images, so fall back to text-only
                    if self.logger:
                        self.logger.warning(
                            f"""{hilight("[AI-Error]", "fail")} {self.config.name} failed to evaluate {hilight(listing.title)} with image, retrying without image: {e}"""
                        )
                    image = None
                    continue
                if self.logger:
                    self.logger.error(
                        f"""{hilight("[AI-Error]", "fail")} {self.config.name} failed to evaluate {hilight(listing.title)}: {e}"""
                    )
                retries += 1
                delay = self.retry_delay(e)
                self.client = None
                time.sleep(delay)

        if response is None:
            raise RuntimeError(
                f"{self.config.name} failed to evaluate {listing.title} after {retries} retries"
            ) from last_error

        answer = response.content[0].text if response.content else ""
        if self.logger:
            self.logger.debug(
                f"""{hilight("[AI-Response]", "info")} {answer}{token_usage(response)}"""
            )
        if (
            answer is None
            or not answer.strip()
            or re.search(r"Rating[^1-5]*[1-5]", answer, re.DOTALL) is None
        ):
            counter.increment(CounterItem.FAILED_AI_QUERY, item_config.name)
            raise ValueError(f"Empty or invalid response from {self.config.name}: {response}")

        score, comment = rating_and_comment(answer)
        res = AIResponse(name=self.config.name, score=score, comment=comment)
        res.to_cache(listing, item_config, marketplace_config)
        counter.increment(CounterItem.NEW_AI_QUERY, item_config.name)
        return res

    def _user_message(
        self: "AnthropicBackend", prompt: str, image: ListingImage | None
    ) -> dict[str, Any]:
        if image is None:
            return {"role": "user", "content": prompt}
        return {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": image.data,
                    },
                },
                {"type": "text", "text": f"{prompt}\n{IMAGE_NOTE}"},
            ],
        }


class SubscriptionError(RuntimeError):
    """A failed request to a subscription CLI; ``status_code`` is the API's HTTP status, if any."""

    def __init__(self: "SubscriptionError", message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SubscriptionBackend(AIBackend):
    """An AI CLI signed in with a subscription, e.g. ``claude -p``, instead of an API key.

    Listings are written by strangers, so whatever the command:

    - The prompt goes to the command's standard input, never into its arguments, and the
      command runs without a shell.
    - It runs in an empty temporary directory, removed afterwards, and its whole process group
      is killed at the timeout.
    - Variables of BILLING_ENV are removed from its environment (unless kept with keep_env), so
      it bills the subscription rather than an API key that happens to be set.
    - Options that let an agent act without asking are refused (see SubscriptionConfig).
    - Its answer is only read for the rating.

    ``claude`` has a profile: aimm adds the options that remove its tools, MCP servers,
    settings (hooks), skills and session, and sends the listing photo through its stream-json
    input. Any other command runs only with ``allow_any_command = true``, which says it cannot
    act on its own; its standard output is the answer, and ``{image}`` in its arguments is
    replaced by the path of the listing photo (otherwise the listing is sent as text only).
    """

    # a smaller photo is enough, and uses less of the usage limit
    image_max_side = 400
    # seconds for one request when the section sets no timeout; a CLI starts in a few
    default_timeout = 180

    @classmethod
    def get_config(cls: Type["SubscriptionBackend"], **kwargs: Any) -> SubscriptionConfig:
        return SubscriptionConfig(**kwargs)

    @property
    def argv(self: "SubscriptionBackend") -> List[str]:
        return command_argv(getattr(self.config, "command", None))

    @property
    def label(self: "SubscriptionBackend") -> str:
        """The command as shown to the user, e.g. in the configure probe."""
        return " ".join(self.argv) or "subscription"

    def connect(self: "SubscriptionBackend") -> None:
        if self.client is None:
            argv = self.argv
            path = shutil.which(argv[0]) if argv else None
            if path is None:
                raise RuntimeError(
                    f"{self.config.name}: the command {argv[0] if argv else ''!r} was not found. "
                    "Install it and sign in, or give its full path in `command`."
                )
            # the client is the path of the command
            self.client = path
            if self.logger:
                self.logger.info(f"""{hilight("[AI]", "name")} {self.config.name} connected.""")

    def command_line(
        self: "SubscriptionBackend", system: str, image_path: str | None = None
    ) -> List[str]:
        """The arguments for one request with the ``system`` prompt."""
        argv = [self.client, *self.argv[1:]]
        if is_claude(self.argv):
            return [
                *argv,
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--verbose",  # required by --output-format stream-json
                "--tools",
                "",
                "--strict-mcp-config",
                "--setting-sources",
                "",
                "--disable-slash-commands",
                "--no-session-persistence",
                "--system-prompt",
                system,
            ]
        if image_path:
            return [a.replace("{image}", image_path) for a in argv]
        # no photo: drop "{image}", and the option before it ("-i {image}")
        out: List[str] = []
        for arg in argv:
            if arg == "{image}":
                if out and out[-1].startswith("-") and len(out) > 1:
                    out.pop()
                continue
            out.append(arg)
        return out

    def _environment(self: "SubscriptionBackend") -> Dict[str, str]:
        keep = set(getattr(self.config, "keep_env", []) or [])
        return {k: v for k, v in os.environ.items() if k not in BILLING_ENV or k in keep}

    def _stdin(
        self: "SubscriptionBackend", prompt: str, system: str, image: ListingImage | None
    ) -> str:
        if not is_claude(self.argv):
            # other CLIs have no system prompt option in common: it leads the prompt
            note = f"\n{IMAGE_NOTE}" if image is not None and self._takes_image else ""
            return f"{system}\n\n{prompt}{note}"
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image is not None:
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": image.data,
                    },
                },
                {"type": "text", "text": f"{prompt}\n{IMAGE_NOTE}"},
            ]
        return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"

    @property
    def _takes_image(self: "SubscriptionBackend") -> bool:
        return is_claude(self.argv) or any("{image}" in a for a in self.argv)

    def ask(
        self: "SubscriptionBackend",
        prompt: str,
        system: str,
        image: ListingImage | None = None,
        timeout: float | None = None,
    ) -> str:
        """The command's answer to ``prompt``; raises SubscriptionError when it fails."""
        if not self._takes_image:
            image = None
        timeout = timeout or self.config.timeout or self.default_timeout
        with tempfile.TemporaryDirectory(prefix="aimm-ai-") as cwd:
            image_path = None
            if image is not None and not is_claude(self.argv):
                image_path = os.path.join(cwd, "listing.jpg")
                with open(image_path, "wb") as f:
                    f.write(base64.b64decode(image.data))
            stdout, stderr, returncode = self._run(
                self.command_line(system, image_path),
                self._stdin(prompt, system, image),
                cwd,
                timeout,
            )
        if not is_claude(self.argv):
            if returncode != 0 or not stdout.strip():
                tail = (stderr or stdout).strip()[-300:]
                raise SubscriptionError(f"{self.argv[0]} exited with {returncode}: {tail}")
            return stdout.strip()
        result: Dict[str, Any] | None = None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                result = event
        if result is None:
            tail = (stderr or stdout).strip()[-300:]
            raise SubscriptionError(f"claude exited with {returncode}: {tail}")
        if result.get("is_error"):
            status = result.get("api_error_status")
            raise SubscriptionError(
                str(result.get("result") or result.get("subtype") or "claude failed"),
                status if isinstance(status, int) else None,
            )
        return str(result.get("result") or "")

    def _run(
        self: "SubscriptionBackend", argv: List[str], stdin: str, cwd: str, timeout: float
    ) -> Tuple[str, str, int]:
        """Run without a shell, in its own process group, killed as a whole at the timeout."""
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=self._environment(),
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise SubscriptionError(
                f"{os.path.basename(argv[0])} did not answer in {timeout:g} seconds"
            ) from None
        return stdout, stderr, process.returncode

    def summarize(self: "SubscriptionBackend", prompt: str) -> str:
        return self._summarize_with(
            lambda: self.ask(prompt, SUMMARY_SYSTEM, timeout=SUMMARY_TIMEOUT)
        )

    def evaluate(
        self: "SubscriptionBackend",
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
    ) -> AIResponse:
        counter.increment(CounterItem.AI_QUERY, item_config.name)
        prompt = self.get_prompt(listing, item_config, marketplace_config)
        res: AIResponse | None = AIResponse.from_cache(listing, item_config, marketplace_config)
        if res is not None:
            if self.logger:
                self.logger.debug(
                    f"""{hilight("[AI]", res.style)} {self.config.name} previously concluded {hilight(f"{res.conclusion} ({res.score}): {res.comment}", res.style)} for listing {hilight(listing.title)}."""
                )
            return res

        retries = 0
        answer: str | None = None
        last_error: Exception | None = None
        image = self.listing_image(listing) if self._takes_image else None
        while retries < self.config.max_retries:
            self.connect()
            self.wait_for_rate_limit()
            try:
                answer = self.ask(
                    prompt,
                    "You are a helpful assistant that can confirm if a user's search criteria matches the item he is interested in.",
                    image,
                )
                break
            except KeyboardInterrupt:
                raise
            except Exception as e:
                last_error = e
                if self.logger:
                    self.logger.error(
                        f"""{hilight("[AI-Error]", "fail")} {self.config.name} failed to evaluate {hilight(listing.title)}: {e}"""
                    )
                retries += 1
                delay = self.retry_delay(e)
                time.sleep(delay)

        if answer is None:
            raise RuntimeError(
                f"{self.config.name} failed to evaluate {listing.title} after {retries} retries"
            ) from last_error

        if self.logger:
            self.logger.debug(f"""{hilight("[AI-Response]", "info")} {answer}""")
        if not answer.strip() or re.search(r"Rating[^1-5]*[1-5]", answer, re.DOTALL) is None:
            counter.increment(CounterItem.FAILED_AI_QUERY, item_config.name)
            raise ValueError(f"Empty or invalid response from {self.config.name}: {answer}")

        score, comment = rating_and_comment(answer)
        res = AIResponse(name=self.config.name, score=score, comment=comment)
        res.to_cache(listing, item_config, marketplace_config)
        counter.increment(CounterItem.NEW_AI_QUERY, item_config.name)
        return res
