import base64
import io
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from logging import Logger
from typing import Any, ClassVar, Generic, Optional, Type, TypeVar

import requests  # type: ignore
from diskcache import Cache  # type: ignore
from PIL import Image
from rich.pretty import pretty_repr

from .listing import Listing
from .marketplace import TItemConfig, TMarketplaceConfig, resolve_option
from .utils import BaseConfig, CacheType, CounterItem, cache, counter, hilight


class AIServiceProvider(Enum):
    OPENAI = "OpenAI"
    DEEPSEEK = "DeepSeek"
    GEMINI = "Gemini"
    ANTHROPIC = "Anthropic"
    OLLAMA = "Ollama"
    UNITYSVC = "UnitySVC"


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
            (CacheType.AI_INQUIRY.value, item_config.hash, marketplace_config.hash, listing.hash)
        )
        if res is None:
            return None
        return AIResponse(**res)

    def to_cache(
        self: "AIResponse",
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
        local_cache: Cache | None = None,
    ) -> None:
        (cache if local_cache is None else local_cache).set(
            (CacheType.AI_INQUIRY.value, item_config.hash, marketplace_config.hash, listing.hash),
            asdict(self),
            tag=CacheType.AI_INQUIRY.value,
        )


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


def fetch_listing_image(url: str, timeout: int = 15) -> ListingImage:
    """Download a listing photo and shrink it so its longest side is at most IMAGE_MAX_SIDE.

    The photo is sent to the AI as data rather than as its URL: Facebook photo URLs expire,
    and not every AI service fetches image URLs.
    """
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    with Image.open(io.BytesIO(response.content)) as img:
        img.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=85)
    return ListingImage("image/jpeg", base64.b64encode(buffer.getvalue()).decode("ascii"))


class AIBackend(Generic[TAIConfig]):
    def __init__(self: "AIBackend", config: AIConfig, logger: Logger | None = None) -> None:
        self.config = config
        self.logger = logger
        self.client: Any = None

    @classmethod
    def get_config(cls: Type["AIBackend"], **kwargs: Any) -> TAIConfig:
        raise NotImplementedError("get_config method must be implemented by subclasses.")

    def connect(self: "AIBackend") -> None:
        raise NotImplementedError("Connect method must be implemented by subclasses.")

    def listing_image(self: "AIBackend", listing: Listing) -> ListingImage | None:
        """The listing's main photo for the AI, or None if not wanted or not available."""
        if not self.config.use_images or not listing.image:
            return None
        try:
            return fetch_listing_image(listing.image)
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
                "1 - No match: Missing key details, wrong category/brand, or suspicious activity (e.g., external links).\n"
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
                default_headers={
                    "X-Title": "AI Marketplace Monitor",
                    "HTTP-Referer": "https://github.com/BoPeng/ai-marketplace-monitor",
                },
            )
            if self.logger:
                self.logger.info(f"""{hilight("[AI]", "name")} {self.config.name} connected.""")

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
                if image is not None:
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
                # try to initiate a connection
                self.client = None
                time.sleep(5)

        if response is None:
            raise RuntimeError(
                f"{self.config.name} failed to evaluate {listing.title} after {retries} retries"
            ) from last_error

        # check if the response is yes
        if self.logger:
            self.logger.debug(f"""{hilight("[AI-Response]", "info")} {pretty_repr(response)}""")

        answer = response.choices[0].message.content or ""
        if (
            answer is None
            or not answer.strip()
            or re.search(r"Rating[^1-5]*[1-5]", answer, re.DOTALL) is None
        ):
            counter.increment(CounterItem.FAILED_AI_QUERY, item_config.name)
            raise ValueError(f"Empty or invalid response from {self.config.name}: {response}")

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

        # remove multiple spaces, take first 30 words
        comment = " ".join([x for x in comment.split() if x.strip()]).strip()
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

    @classmethod
    def get_config(cls: Type["AnthropicBackend"], **kwargs: Any) -> AnthropicConfig:
        return AnthropicConfig(**kwargs)

    def connect(self: "AnthropicBackend") -> None:
        if self.client is None:
            import anthropic  # type: ignore

            self.client = anthropic.Anthropic(
                api_key=self.config.api_key,
                timeout=self.config.timeout,
            )
            if self.logger:
                self.logger.info(f"""{hilight("[AI]", "name")} {self.config.name} connected.""")

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
        image = self.listing_image(listing)
        while retries < self.config.max_retries:
            self.connect()
            assert self.client is not None
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
                if image is not None:
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
                self.client = None
                time.sleep(5)

        if self.logger:
            self.logger.debug(f"""{hilight("[AI-Response]", "info")} {pretty_repr(response)}""")

        answer = response.content[0].text if response.content else ""
        if (
            answer is None
            or not answer.strip()
            or re.search(r"Rating[^1-5]*[1-5]", answer, re.DOTALL) is None
        ):
            counter.increment(CounterItem.FAILED_AI_QUERY, item_config.name)
            raise ValueError(f"Empty or invalid response from {self.config.name}: {response}")

        lines = answer.split("\n")
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
                comment += " " + line
        if len(comment.strip()) < 5 and rating_line is not None and rating_line > 0:
            comment = lines[rating_line - 1]

        comment = " ".join([x for x in comment.split() if x.strip()]).strip()
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
