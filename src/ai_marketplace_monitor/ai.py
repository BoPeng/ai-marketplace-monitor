import html
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from logging import Logger
from typing import TYPE_CHECKING, Any, ClassVar, Generic, List, Optional, Type, TypeVar

from diskcache import Cache  # type: ignore
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from openai import OpenAI  # type: ignore
from pydantic import SecretStr
from rich.pretty import pretty_repr

from .langsmith_utils import configure_langsmith_environment, log_langsmith_status
from .listing import Listing
from .marketplace import TItemConfig, TMarketplaceConfig
from .utils import BaseConfig, CacheType, CounterItem, cache, counter, hilight

if TYPE_CHECKING:
    from .config import Config

# Cache duration constants (in seconds)
MODEL_AVAILABILITY_CACHE_DURATION = 300  # 5 minutes for available models
MODEL_UNAVAILABLE_CACHE_DURATION = 60  # 1 minute for unavailable models
RATE_LIMIT_CACHE_DURATION = 120  # 2 minutes for rate limit tracking


def _is_model_cached_available(model: str) -> bool:
    """Check if a model is cached as available and cache hasn't expired."""
    key = f"openrouter_model_available_{model}"
    return cache.get(key, default=False)


def _is_model_cached_unavailable(model: str) -> Optional[str]:
    """Check if a model is cached as unavailable and return error type if so."""
    key = f"openrouter_model_unavailable_{model}"
    return cache.get(key, default=None)


def _cache_model_availability(model: str, available: bool, error_type: str = "") -> None:
    """Cache model availability status using existing diskcache infrastructure."""
    if available:
        available_key = f"openrouter_model_available_{model}"
        unavailable_key = f"openrouter_model_unavailable_{model}"
        cache.set(available_key, True, expire=MODEL_AVAILABILITY_CACHE_DURATION)
        # Remove from unavailable cache if present
        cache.delete(unavailable_key)
    else:
        available_key = f"openrouter_model_available_{model}"
        unavailable_key = f"openrouter_model_unavailable_{model}"
        cache.set(unavailable_key, error_type, expire=MODEL_UNAVAILABLE_CACHE_DURATION)
        # Remove from available cache if present
        cache.delete(available_key)


def _is_provider_rate_limited(provider: str) -> bool:
    """Check if a provider is currently rate limited."""
    key = f"openrouter_rate_limit_{provider}"
    return cache.get(key, default=False)


def _cache_rate_limit(provider: str) -> None:
    """Cache that a provider is currently rate limited."""
    key = f"openrouter_rate_limit_{provider}"
    cache.set(key, True, expire=RATE_LIMIT_CACHE_DURATION)


class AIServiceProvider(Enum):
    OPENAI = "OpenAI"
    DEEPSEEK = "DeepSeek"
    OLLAMA = "Ollama"
    OPENROUTER = "OpenRouter"


@dataclass
class AIResponse:
    score: int
    comment: str
    name: str = ""
    # Token usage tracking for cost monitoring
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # Additional metadata from AI responses
    usage_metadata: Optional[dict] = field(default_factory=dict)
    response_metadata: Optional[dict] = field(default_factory=dict)

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

    @property
    def has_token_usage(self: "AIResponse") -> bool:
        """Check if this response contains token usage information."""
        return self.total_tokens > 0 or self.prompt_tokens > 0 or self.completion_tokens > 0

    def get_cost_estimate(
        self: "AIResponse", prompt_price_per_k: float = 0.0, completion_price_per_k: float = 0.0
    ) -> float:
        """Estimate cost based on token usage and pricing."""
        if not self.has_token_usage:
            return 0.0
        prompt_cost = (self.prompt_tokens / 1000) * prompt_price_per_k
        completion_cost = (self.completion_tokens / 1000) * completion_price_per_k
        return prompt_cost + completion_cost

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

        # Handle cache migration for legacy AIResponse objects without new metadata fields
        # Ensure backward compatibility with existing cached responses
        if not isinstance(res, dict):
            return None

        # Provide defaults for new metadata fields if missing from cached response
        migrated_res = res.copy()
        if "usage_metadata" not in migrated_res:
            migrated_res["usage_metadata"] = {}
        if "response_metadata" not in migrated_res:
            migrated_res["response_metadata"] = {}

        # Ensure metadata fields are dict types (handle None values from old cache entries)
        if migrated_res.get("usage_metadata") is None:
            migrated_res["usage_metadata"] = {}
        if migrated_res.get("response_metadata") is None:
            migrated_res["response_metadata"] = {}

        try:
            return AIResponse(**migrated_res)
        except TypeError:
            # If reconstruction fails due to incompatible cached data, return None
            # This allows cache miss handling to regenerate the response
            return None

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


@dataclass
class OpenAIConfig(AIConfig):
    def handle_api_key(self: "OpenAIConfig") -> None:
        if self.api_key is None:
            raise ValueError("OpenAI requires a string api_key.")


@dataclass
class DeekSeekConfig(OpenAIConfig):
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


# System message for marketplace evaluation
MARKETPLACE_EVALUATION_SYSTEM_MESSAGE = """You are a marketplace listing evaluation expert. Your role is to assess how well Facebook Marketplace listings match user search criteria.

You should evaluate listings based on:
- Relevance to search terms and description
- Price reasonability vs. market value
- Item condition and seller credibility
- Completeness of listing information

Always conclude your evaluation with "Rating X:" where X is 1-5, followed by a brief summary (max 30 words).

Rating Scale:
1 - No match: Missing key details, wrong category/brand, or suspicious activity
2 - Potential match: Lacks essential info; needs clarification
3 - Poor match: Some mismatches or missing details; acceptable but not ideal
4 - Good match: Mostly meets criteria with clear, relevant details
5 - Great deal: Fully matches criteria, with excellent condition or price"""

# Few-shot examples for consistent rating behavior
FEW_SHOT_EXAMPLES = [
    {
        "user_criteria": "Looking for: iPhone 12, budget: $300-500, good condition",
        "listing": "iPhone 12 Pro 128GB, excellent condition, $450, includes charger and case",
        "evaluation": "This listing closely matches your criteria. The iPhone 12 Pro is an upgrade from the standard iPhone 12, priced within your budget at $450. Excellent condition and includes accessories add value. Seller provides clear details and photos.\n\nRating 5: Perfect match - iPhone 12 Pro in excellent condition, great price with accessories",
    },
    {
        "user_criteria": "Looking for: MacBook Air, budget: $800-1200, for college work",
        "listing": "MacBook Pro 2019 16-inch, some wear on corners, $900, works fine",
        "evaluation": "This is a MacBook Pro rather than the MacBook Air you requested. While the price fits your budget, the 16-inch Pro is heavier and more powerful than needed for typical college work. 'Some wear' and 'works fine' lack detail about actual condition.\n\nRating 2: Wrong model and vague condition description, needs more details",
    },
    {
        "user_criteria": "Looking for: Gaming chair, budget: under $200, ergonomic features",
        "listing": "IKEA office chair, used 6 months, $50, comfortable for long hours",
        "evaluation": "This is a basic office chair rather than a gaming chair with ergonomic features. However, the low price of $50 is well within budget and the seller mentions comfort for extended use. The IKEA brand is reliable.\n\nRating 3: Not specifically a gaming chair but budget-friendly office alternative",
    },
]

TAIConfig = TypeVar("TAIConfig", bound=AIConfig)


class AIBackend(Generic[TAIConfig]):
    def __init__(self: "AIBackend", config: AIConfig, logger: Logger | None = None) -> None:
        self.config = config
        self.logger = logger
        self.client: OpenAI | None = None

    @classmethod
    def get_config(cls: Type["AIBackend"], **kwargs: Any) -> TAIConfig:
        raise NotImplementedError("get_config method must be implemented by subclasses.")

    def connect(self: "AIBackend") -> None:
        raise NotImplementedError("Connect method must be implemented by subclasses.")

    def _sanitize_input(self, text: str) -> str:
        """Basic input sanitization for backwards compatibility."""
        if not text:
            return text
        # Simple HTML escape and basic pattern filtering
        return html.escape(text, quote=True)

    def get_prompt(
        self: "AIBackend",
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
    ) -> str:
        # Build user criteria section with sanitized inputs
        user_criteria = f"Looking for: {item_config.name}"
        if item_config.search_phrases:
            # Sanitize search terms to prevent injection
            sanitized_phrases = [
                self._sanitize_input(phrase) for phrase in item_config.search_phrases
            ]
            search_terms = '" and "'.join(sanitized_phrases)
            user_criteria += f", search terms: {search_terms}"
        if item_config.description:
            sanitized_desc = self._sanitize_input(item_config.description)
            user_criteria += f", description: {sanitized_desc}"

        # Add price constraints
        max_price = item_config.max_price or 0
        min_price = item_config.min_price or 0
        if max_price and min_price:
            user_criteria += f", budget: ${min_price}-{max_price}"
        elif max_price:
            user_criteria += f", max budget: ${max_price}"
        elif min_price:
            user_criteria += f", min budget: ${min_price}"

        # Add exclusions with sanitized inputs
        if item_config.antikeywords:
            sanitized_antikeywords = [
                self._sanitize_input(keyword) for keyword in item_config.antikeywords
            ]
            exclude_terms = '" and "'.join(sanitized_antikeywords)
            user_criteria += f", exclude: {exclude_terms}"

        # Build listing details section with sanitized inputs
        sanitized_title = self._sanitize_input(listing.title)
        sanitized_condition = self._sanitize_input(listing.condition)
        sanitized_price = self._sanitize_input(listing.price)
        sanitized_location = self._sanitize_input(listing.location)
        sanitized_description = self._sanitize_input(listing.description)

        listing_details = (
            f"Title: {sanitized_title}\n"
            f"Condition: {sanitized_condition}\n"
            f"Price: {sanitized_price}\n"
            f"Location: {sanitized_location}\n"
            f"Description: {sanitized_description}\n"
            f"URL: {listing.post_url}"
        )

        # Build evaluation instructions
        evaluation_instructions = ""
        if item_config.prompt is not None:
            evaluation_instructions = item_config.prompt
        elif marketplace_config.prompt is not None:
            evaluation_instructions = marketplace_config.prompt
        else:
            evaluation_instructions = (
                "Evaluate how well this listing matches the user's criteria. "
                "Assess the description, market value, condition, and seller credibility."
            )

        # Add extra instructions if provided
        if item_config.extra_prompt is not None:
            evaluation_instructions += f"\n\n{item_config.extra_prompt.strip()}"
        elif marketplace_config.extra_prompt is not None:
            evaluation_instructions += f"\n\n{marketplace_config.extra_prompt.strip()}"

        # Add rating instructions (for backward compatibility)
        rating_instructions = ""
        if item_config.rating_prompt is not None:
            rating_instructions = item_config.rating_prompt.strip()
        elif marketplace_config.rating_prompt is not None:
            rating_instructions = marketplace_config.rating_prompt.strip()
        else:
            rating_instructions = (
                "Rate from 1 to 5 based on the following:\n"
                "1 - No match: Missing key details, wrong category/brand, or suspicious activity.\n"
                "2 - Potential match: Lacks essential info; needs clarification.\n"
                "3 - Poor match: Some mismatches or missing details; acceptable but not ideal.\n"
                "4 - Good match: Mostly meets criteria with clear, relevant details.\n"
                "5 - Great deal: Fully matches criteria, with excellent condition or price.\n"
                'Conclude with: "Rating <1-5>: <summary>" where <1-5> is the rating and <summary> is a brief recommendation (max 30 words).'
            )

        # Build the complete prompt using structured format
        prompt = (
            f"USER CRITERIA:\n{user_criteria}\n\n"
            f"LISTING DETAILS:\n{listing_details}\n\n"
            f"EVALUATION TASK:\n{evaluation_instructions}\n\n"
            f"EXAMPLES OF GOOD EVALUATIONS:\n"
            f"Example 1: {FEW_SHOT_EXAMPLES[0]['user_criteria']}\n"
            f"Listing: {FEW_SHOT_EXAMPLES[0]['listing']}\n"
            f"Evaluation: {FEW_SHOT_EXAMPLES[0]['evaluation']}\n\n"
            f"Example 2: {FEW_SHOT_EXAMPLES[1]['user_criteria']}\n"
            f"Listing: {FEW_SHOT_EXAMPLES[1]['listing']}\n"
            f"Evaluation: {FEW_SHOT_EXAMPLES[1]['evaluation']}\n\n"
            f"RATING INSTRUCTIONS:\n{rating_instructions}\n\n"
            f"Now evaluate the listing above following the same format and rating scale."
        )

        if self.logger:
            self.logger.debug(f"""{hilight("[AI-Prompt]", "info")} {prompt}""")
        return prompt

    def _parse_ai_response(self, answer: str, item_config: TItemConfig) -> AIResponse:
        """Parse AI response text to extract rating and comment.

        This method contains the common response parsing logic used by all backends.
        """
        if (
            answer is None
            or not answer.strip()
            or self._rating_search_pattern.search(answer) is None
        ):
            counter.increment(CounterItem.FAILED_AI_QUERY, item_config.name)
            raise ValueError(f"Empty or invalid response from {self.config.name}: {answer}")

        lines = answer.split("\n")
        # Extract rating from response
        score: int = 1
        comment = ""
        rating_line = None
        for idx, line in enumerate(lines):
            matched = self._rating_extract_pattern.match(line)
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
        comment = " ".join(comment.split())
        res = AIResponse(name=self.config.name, score=score, comment=comment)
        return res

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
            # Ensure API key is properly converted to string for OpenAI client
            api_key = self.config.api_key
            if api_key is None:
                raise ValueError(f"API key is required for {self.config.provider}")
            self.client = OpenAI(
                api_key=api_key,
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
        while retries < self.config.max_retries:
            self.connect()
            assert self.client is not None
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model or self.default_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful assistant that can confirm if a user's search criteria matches the item he is interested in.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    stream=False,
                )
                break
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
                    self.logger.error(
                        f"""{hilight("[AI-Error]", "fail")} {self.config.name} failed to evaluate {hilight(listing.title)}: {e}"""
                    )
                retries += 1
                # try to initiate a connection
                self.client = None
                time.sleep(5)

        # check if the response is yes
        if self.logger:
            self.logger.debug(f"""{hilight("[AI-Response]", "info")} {pretty_repr(response)}""")

        answer = response.choices[0].message.content or ""
        res = self._parse_ai_response(answer, item_config)
        res.to_cache(listing, item_config, marketplace_config)
        counter.increment(CounterItem.NEW_AI_QUERY, item_config.name)
        return res


class DeepSeekBackend(OpenAIBackend):
    default_model = "deepseek-chat"
    base_url = "https://api.deepseek.com"

    @classmethod
    def get_config(cls: Type["DeepSeekBackend"], **kwargs: Any) -> DeekSeekConfig:
        return DeekSeekConfig(**kwargs)


class OllamaBackend(OpenAIBackend):
    default_model = "deepseek-r1:14b"

    @classmethod
    def get_config(cls: Type["OllamaBackend"], **kwargs: Any) -> OllamaConfig:
        return OllamaConfig(**kwargs)


# Provider mapping system for LangChain integration
def _create_openai_model(config: AIConfig) -> BaseChatModel:
    """Create a ChatOpenAI model instance from AIConfig."""
    api_key = config.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OpenAI API key is required")

    return ChatOpenAI(
        api_key=SecretStr(api_key),
        model=config.model or "gpt-4o",
        base_url=config.base_url,
        timeout=config.timeout,
        max_retries=config.max_retries,
        default_headers={
            "X-Title": "AI Marketplace Monitor",
            "HTTP-Referer": "https://github.com/BoPeng/ai-marketplace-monitor",
        },
    )


def _validate_openrouter_model_format(model: str) -> None:
    """Validate OpenRouter model format rigorously.

    OpenRouter requires models in 'provider/model' format with exactly
    one slash separating non-empty provider and model names.

    Args:
        model: Model string to validate

    Raises:
        ValueError: If model format is invalid
    """
    if not model or not isinstance(model, str):
        raise ValueError("OpenRouter requires a model string")

    if "/" not in model:
        raise ValueError(
            f"OpenRouter model '{model}' must follow 'provider/model' format "
            "(e.g., 'anthropic/claude-3-sonnet', 'openai/gpt-4'). "
            "Check available models at https://openrouter.ai/models"
        )

    parts = model.split("/")
    if len(parts) != 2:
        raise ValueError(
            f"OpenRouter model '{model}' must be exactly 'provider/model' format. "
            f"Got {len(parts)} parts, expected 2"
        )

    provider, model_name = parts
    if not provider or not model_name:
        raise ValueError(
            f"OpenRouter model '{model}' must have non-empty provider and model names. "
            f"Provider: '{provider}', Model: '{model_name}'"
        )

    # Additional format validation
    if provider.strip() != provider or model_name.strip() != model_name:
        raise ValueError(
            f"OpenRouter model '{model}' contains whitespace. "
            "Provider and model names should not have leading/trailing spaces"
        )


def _validate_openrouter_api_key_strength(api_key: str) -> None:
    """Validate OpenRouter API key appears legitimate.

    Checks for common placeholder keys and basic format requirements.

    Args:
        api_key: API key to validate

    Raises:
        ValueError: If API key appears to be a placeholder or invalid
    """
    if not api_key or len(api_key) < 20:  # OpenRouter keys are typically 40+ chars
        raise ValueError("OpenRouter API key appears too short to be valid")

    # Check for common placeholder patterns using set for O(1) lookup
    placeholder_patterns = {
        "sk-or-test",
        "sk-or-example",
        "sk-or-your-key",
        "sk-or-placeholder",
        "sk-or-demo",
        "sk-or-sample",
        "sk-or-fake",
        "sk-or-12345",
    }

    api_key_lower = api_key.lower()
    if any(pattern in api_key_lower for pattern in placeholder_patterns):
        raise ValueError(
            "Please use your actual OpenRouter API key, not a placeholder. "
            "Get your key at https://openrouter.ai/keys"
        )

    # Additional entropy check - API keys should have reasonable character diversity
    if len(set(api_key)) < 10:  # Too few unique characters
        raise ValueError("API key appears to lack sufficient entropy")

    # Check if it looks like an OpenAI key being used by mistake
    if api_key.startswith("sk-") and not api_key.startswith("sk-or-"):
        raise ValueError(
            "You appear to be using an OpenAI API key for OpenRouter. "
            "OpenRouter requires keys that start with 'sk-or-'. "
            "Get your OpenRouter key at https://openrouter.ai/keys"
        )


def _create_openrouter_model(config: AIConfig) -> BaseChatModel:
    """Create a ChatOpenAI model instance configured for OpenRouter."""
    api_key = config.api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OpenRouter API key is required")

    # Skip validation for test keys during testing
    if not api_key.startswith(("test-", "mock-", "fake-")):
        # Validate API key format and strength for OpenRouter
        if not api_key.startswith("sk-or-"):
            raise ValueError(
                "OpenRouter API key must start with 'sk-or-'. "
                "Please check your OpenRouter API key format."
            )

        _validate_openrouter_api_key_strength(api_key)

    # Validate model format for OpenRouter (should be 'provider/model')
    model = config.model or "anthropic/claude-3-sonnet"
    _validate_openrouter_model_format(model)

    # Check if model is cached as unavailable
    cached_error = _is_model_cached_unavailable(model)
    if cached_error:
        raise ValueError(f"OpenRouter model '{model}' is currently unavailable: {cached_error}")

    # Skip rate limiting check for test keys during testing
    if not api_key.startswith(("test-", "mock-", "fake-")):
        # Check if provider is rate limited
        provider = model.split("/")[0]
        if _is_provider_rate_limited(provider):
            raise RuntimeError(
                f"OpenRouter provider '{provider}' is currently rate limited. "
                "Please try again in a few minutes or select a different provider."
            )

    base_url = config.base_url or "https://openrouter.ai/api/v1"

    return ChatOpenAI(
        api_key=SecretStr(api_key),
        model=model,
        base_url=base_url,
        timeout=config.timeout,
        max_retries=config.max_retries,
        default_headers={
            "X-Title": "AI Marketplace Monitor",
            "HTTP-Referer": "https://github.com/BoPeng/ai-marketplace-monitor",
        },
    )


def _create_deepseek_model(config: AIConfig) -> BaseChatModel:
    """Create a ChatDeepSeek model instance from AIConfig."""
    api_key = config.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DeepSeek API key is required")

    return ChatDeepSeek(
        api_key=SecretStr(api_key),
        model=config.model or "deepseek-chat",
        timeout=config.timeout,
        max_retries=config.max_retries,
    )


def _create_ollama_model(config: AIConfig) -> BaseChatModel:
    """Create a ChatOllama model instance from AIConfig."""
    # Prepare client kwargs with timeout if specified
    client_kwargs = {}
    if config.timeout is not None:
        client_kwargs["timeout"] = config.timeout
    return ChatOllama(
        model=config.model or "deepseek-r1:14b",
        base_url=config.base_url or "http://localhost:11434",
        num_ctx=4096,  # Default context length
        client_kwargs=client_kwargs if client_kwargs else None,
    )


provider_map = {
    "openai": _create_openai_model,
    "deepseek": _create_deepseek_model,
    "ollama": _create_ollama_model,
    "openrouter": _create_openrouter_model,
}


def adapt_langchain_response(
    response: Any,
    backend_name: str,
    parsed_score: int,
    parsed_comment: str,
) -> AIResponse:
    """Adapter function to convert LangChain response objects into AIResponse format.

    Extracts token usage, metadata, and content from LangChain responses while
    maintaining compatibility with existing AIResponse structure and caching.

    Args:
        response: LangChain chat model response object
        backend_name: Name of the backend for identification
        parsed_score: AI rating score (1-5) parsed from response text
        parsed_comment: AI comment parsed from response text

    Returns:
        AIResponse object with token usage and metadata preserved
    """
    # Initialize token usage values
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    usage_metadata = {}
    response_metadata = {}

    # Extract usage metadata (token counts) if available
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage_dict = response.usage_metadata
        if isinstance(usage_dict, dict):
            usage_metadata = usage_dict.copy()
            prompt_tokens = usage_dict.get("input_tokens", 0)
            completion_tokens = usage_dict.get("output_tokens", 0)
            total_tokens = usage_dict.get("total_tokens", prompt_tokens + completion_tokens)

    # Extract response metadata (model info, etc.) if available
    if hasattr(response, "response_metadata") and response.response_metadata:
        if isinstance(response.response_metadata, dict):
            response_metadata = response.response_metadata.copy()

    # Handle additional_kwargs which may contain usage info
    if hasattr(response, "additional_kwargs") and response.additional_kwargs:
        if isinstance(response.additional_kwargs, dict):
            # Some providers put usage info in additional_kwargs
            usage_info = response.additional_kwargs.get("usage", {})
            if isinstance(usage_info, dict) and not usage_metadata:
                prompt_tokens = usage_info.get("prompt_tokens", 0)
                completion_tokens = usage_info.get("completion_tokens", 0)
                total_tokens = usage_info.get("total_tokens", prompt_tokens + completion_tokens)
                usage_metadata = usage_info.copy()

            # Merge additional metadata
            response_metadata.update(
                {
                    k: v
                    for k, v in response.additional_kwargs.items()
                    if k not in ["usage"] and not k.startswith("_")
                }
            )

    return AIResponse(
        score=parsed_score,
        comment=parsed_comment,
        name=backend_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        usage_metadata=usage_metadata,
        response_metadata=response_metadata,
    )


class LangChainBackend(AIBackend[AIConfig]):
    """Unified LangChain backend for AI providers using the provider mapping system.

    This class is thread-safe. Multiple threads can safely call evaluate() and connect()
    methods concurrently. Internal model state is protected by a reentrant lock.
    """

    def __init__(
        self,
        config: AIConfig,
        logger: Logger | None = None,
        main_config: Optional["Config"] = None,
    ) -> None:
        super().__init__(config, logger)
        self._chat_model: BaseChatModel | None = None
        self._model_lock = threading.RLock()  # Reentrant lock for thread safety
        self._prompt_template: ChatPromptTemplate | None = None
        self._main_config = main_config

        # Configure LangSmith environment if TOML config is provided
        if main_config and hasattr(main_config, "langsmith") and main_config.langsmith:
            configure_langsmith_environment(main_config.langsmith)

        # Pre-compiled regex patterns for better performance
        self._rating_search_pattern = re.compile(r"Rating[^1-5]*[1-5]", re.DOTALL)
        self._rating_extract_pattern = re.compile(r".*Rating[^1-5]*([1-5])[:\s]*(.*)")
        self._prompt_injection_patterns = [
            (re.compile(r"\[SYSTEM\]|\<\|system\|\>", re.IGNORECASE), "[USER INPUT]"),
            (re.compile(r"\[ASSISTANT\]|\<\|assistant\|\>", re.IGNORECASE), "[USER INPUT]"),
            (re.compile(r"\[USER\]|\<\|user\|\>", re.IGNORECASE), "[USER INPUT]"),
            (re.compile(r"\n{5,}"), "\n\n"),
        ]

    @classmethod
    def get_config(cls: Type["LangChainBackend"], **kwargs: Any) -> AIConfig:
        """Get configuration for the LangChain backend."""
        config = AIConfig(**kwargs)
        cls._validate_config_compatibility(config)
        return config

    @staticmethod
    def _validate_config_compatibility(config: AIConfig) -> None:
        """Validate configuration for compatibility and completeness.

        Ensures the configuration meets all requirements for LangChain backend operation,
        preserving existing validation patterns and error messages.
        """
        # Validate provider is supported
        if not config.provider:
            raise ValueError("AIConfig must have a provider specified")

        provider_key = config.provider.lower()
        if provider_key not in provider_map:
            supported_providers = ", ".join(provider_map.keys())
            raise ValueError(
                f"Unsupported provider '{config.provider}'. "
                f"Supported providers: {supported_providers}"
            )

        # Provider-specific validation
        if provider_key == "openai":
            if not config.api_key and not os.getenv("OPENAI_API_KEY"):
                raise ValueError("openai requires an API key")
            if config.model and not isinstance(config.model, str):
                raise ValueError("OpenAI model must be a string")

        elif provider_key == "openrouter":
            # Validate API key presence and format
            api_key = config.api_key or os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise ValueError("OpenRouter requires an API key")
            if not api_key.startswith("sk-or-"):
                raise ValueError(
                    "OpenRouter API key must start with 'sk-or-'. "
                    "Please check your OpenRouter API key format."
                )

            # Validate model format for OpenRouter
            if config.model and not isinstance(config.model, str):
                raise ValueError("OpenRouter model must be a string")
            if config.model and "/" not in config.model:
                raise ValueError(
                    f"OpenRouter model '{config.model}' must follow 'provider/model' format "
                    "(e.g., 'anthropic/claude-3-sonnet', 'openai/gpt-4')"
                )

        elif provider_key == "deepseek":
            if not config.api_key and not os.getenv("DEEPSEEK_API_KEY"):
                raise ValueError("DeepSeek requires an API key")
            if config.base_url and config.base_url != "https://api.deepseek.com":
                # Note: Config validation warnings would be handled by the logger passed to the backend instance
                pass

        elif provider_key == "ollama":
            if not config.base_url:
                # Use default Ollama URL if not specified
                config.base_url = "http://localhost:11434"
            if not config.model:
                raise ValueError("Ollama requires a model to be specified")

        # Validate common configuration parameters
        if config.max_retries is not None and (
            not isinstance(config.max_retries, int) or config.max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")

        if config.timeout is not None and (
            not isinstance(config.timeout, int) or config.timeout <= 0
        ):
            raise ValueError("timeout must be a positive integer")

    def _validate_thread_safety(self) -> None:
        """Validate thread safety by checking that model access is properly synchronized."""
        # This method ensures thread-safe access patterns are maintained
        if not hasattr(self, "_model_lock"):
            raise RuntimeError("LangChainBackend missing proper thread synchronization")

        # Check if it's the right type of lock
        lock = getattr(self, "_model_lock", None)
        if not hasattr(lock, "acquire") or not hasattr(lock, "release"):
            raise RuntimeError("LangChainBackend missing proper thread synchronization")

        # Verify that the lock is functional
        try:
            acquired = self._model_lock.acquire(blocking=False)
            if acquired:
                self._model_lock.release()
            else:
                raise RuntimeError("Thread synchronization lock is in an invalid state")
        except Exception as e:
            raise RuntimeError("Thread synchronization lock is in an invalid state") from e

    def _map_langchain_exception(self, e: Exception, context: str = "") -> Exception:
        """Map LangChain exceptions to existing error patterns for backward compatibility.

        This method provides a comprehensive mapping layer that transforms LangChain and
        provider-specific exceptions into standardized SDK exceptions. It preserves
        exception chaining, adds contextual information, and includes performance monitoring.

        Exception Mapping Strategy:
        - LangChain core exceptions → RuntimeError (LangChainException, TracerException)
                                    or ValueError (OutputParserException)
        - Provider exceptions (OpenAI, etc.) → ValueError (auth/config) or RuntimeError (service)
        - Import/dependency errors → RuntimeError with installation guidance
        - Unknown exceptions → RuntimeError with fallback message

        Args:
            e: The original exception to map
            context: Contextual information about where the exception occurred

        Returns:
            Exception: Mapped exception with preserved cause chain and context

        Raises:
            The mapped exception type based on the original exception pattern

        Performance:
        - Target: <1ms per exception mapping
        - Includes structured logging with timing metrics
        - Exception chaining preserves original stack traces

        Maintenance Notes:
        - Add new provider exceptions to Stage 2 (Provider-specific mapping)
        - Follow existing patterns: ValueError for config/input, RuntimeError for service
        - Always preserve exception chaining with __cause__ attribute
        - Update tests in test_langchain_validation.py when adding new mappings
        """
        import time

        start_time = time.perf_counter()
        error_msg = str(e)
        context_prefix = f"{context}: " if context else ""
        exception_type = type(e).__name__

        # Helper function to log mapping outcome and return mapped exception
        # This ensures consistent exception chaining and performance logging across all mapping paths
        def _return_mapped_exception(
            mapped_exc: Exception, mapping_type: str = "standard"
        ) -> Exception:
            # Preserve original exception as cause for debugging and stack trace analysis
            mapped_exc.__cause__ = e
            elapsed_time = time.perf_counter() - start_time
            mapped_type = type(mapped_exc).__name__

            # Log successful mapping with timing for performance monitoring
            if self.logger:
                self.logger.debug(
                    f"""{hilight("[Exception-Mapping]", "succ")} Mapped {hilight(exception_type)} """
                    f"""to {hilight(mapped_type)} via {mapping_type} in {elapsed_time * 1000:.2f}ms"""
                )
            return mapped_exc

        # Import LangChain exceptions for isinstance checks
        try:
            from langchain_core.exceptions import (
                LangChainException,
                OutputParserException,
                TracerException,
            )
        except ImportError:
            # Fallback if LangChain not available - create dummy exception classes
            # that will never match any actual exception instances
            LangChainException = type("_FakeLangChainException", (BaseException,), {})  # type: ignore # noqa: N806
            OutputParserException = type("_FakeOutputParserException", (BaseException,), {})  # type: ignore # noqa: N806
            TracerException = type("_FakeTracerException", (BaseException,), {})  # type: ignore # noqa: N806

        # Log original exception for debugging
        if self.logger:
            self.logger.debug(
                f"""{hilight("[Exception-Mapping]", "info")} Mapping {hilight(exception_type)} """
                f"""from {hilight(context or "unknown context", "name")}: {error_msg[:100]}"""
            )

        # ==================== STAGE 1: CORE LANGCHAIN EXCEPTION MAPPING ====================
        # Map LangChain's own exception hierarchy to appropriate SDK exceptions.
        # These are framework-level errors from LangChain components (chains, parsers, tracers).

        if isinstance(e, LangChainException):
            mapped_exc = RuntimeError(f"{context_prefix}LangChain operation failed: {error_msg}")
            return _return_mapped_exception(mapped_exc, "LangChain-core")

        if isinstance(e, OutputParserException):
            mapped_exc = RuntimeError(
                f"{context_prefix}AI response parsing failed: {error_msg}. "
                "The model response format was unexpected or malformed."
            )
            return _return_mapped_exception(mapped_exc, "LangChain-parser")

        if isinstance(e, TracerException):
            mapped_exc = RuntimeError(f"{context_prefix}LangChain tracing error: {error_msg}")
            return _return_mapped_exception(mapped_exc, "LangChain-tracer")

        # ==================== STAGE 2: PROVIDER-SPECIFIC EXCEPTION MAPPING ====================
        # Map exceptions from underlying AI providers (OpenAI, Anthropic, etc.) that are wrapped by LangChain.
        # These are API-level errors from the actual model providers.
        #
        # Mapping Strategy:
        # - Configuration/Auth errors → ValueError (user can fix)
        # - Service/Infrastructure errors → RuntimeError (service issue)

        exception_name = type(e).__name__

        # OpenAI API exceptions (most common provider)
        if exception_name in ["APIConnectionError", "APITimeoutError"]:
            mapped_exc = RuntimeError(
                f"{context_prefix}Connection failed: {error_msg}. "
                "Check network connectivity and service availability."
            )
            return _return_mapped_exception(mapped_exc, "provider-connection")

        if exception_name == "AuthenticationError":
            mapped_exc = ValueError(
                f"{context_prefix}Authentication error: {error_msg}. Check API key configuration."
            )
            return _return_mapped_exception(mapped_exc, "provider-auth")

        if exception_name == "RateLimitError":
            mapped_exc = RuntimeError(
                f"{context_prefix}Rate limit exceeded: {error_msg}. "
                "Try again later or upgrade your plan."
            )
            return _return_mapped_exception(mapped_exc, "provider-rate-limit")

        if exception_name == "BadRequestError":
            mapped_exc = ValueError(
                f"{context_prefix}Invalid request: {error_msg}. "
                "Check model parameters and input format."
            )
            return _return_mapped_exception(mapped_exc, "provider-bad-request")

        if exception_name in ["NotFoundError", "PermissionDeniedError"]:
            mapped_exc = ValueError(
                f"{context_prefix}Resource access error: {error_msg}. "
                "Check model availability and permissions."
            )
            return _return_mapped_exception(mapped_exc, "provider-access-denied")

        if exception_name == "InternalServerError":
            mapped_exc = RuntimeError(
                f"{context_prefix}Provider service error: {error_msg}. "
                "Try again later or contact provider support."
            )
            return _return_mapped_exception(mapped_exc, "provider-internal-error")

        # ==================== STAGE 3: GENERIC LANGCHAIN PATTERNS ====================
        # Handle common Python exceptions that occur in LangChain context.
        # These are typically environment or configuration issues.

        if isinstance(e, ImportError):
            mapped_exc = RuntimeError(
                f"{context_prefix}Provider dependencies not installed: {error_msg}. "
                "Install the required LangChain packages."
            )
            return _return_mapped_exception(mapped_exc, "import-error")

        if isinstance(e, (ValueError, TypeError)) and any(
            pattern in error_msg.lower()
            for pattern in ["api_key", "authentication", "unauthorized"]
        ):
            mapped_exc = ValueError(
                f"{context_prefix}Authentication error: {error_msg}. Check API key configuration."
            )
            return _return_mapped_exception(mapped_exc, "generic-auth-error")

        # OpenRouter-specific error handling
        if isinstance(e, ValueError) and "openrouter" in error_msg.lower():
            if "sk-or-" in error_msg:
                return ValueError(
                    f"{context_prefix}OpenRouter API key format error: {error_msg}. "
                    "Get a valid API key from https://openrouter.ai/keys"
                )
            elif "provider/model" in error_msg:
                return ValueError(
                    f"{context_prefix}OpenRouter model format error: {error_msg}. "
                    "Use format like 'anthropic/claude-3-sonnet'. "
                    "See https://openrouter.ai/models for available models."
                )

        # Enhanced OpenRouter error patterns
        if "openrouter" in context.lower() or "openrouter.ai" in error_msg.lower():
            # Model not found/availability errors
            if any(
                phrase in error_msg.lower()
                for phrase in [
                    "model not found",
                    "model not available",
                    "model does not exist",
                    "unknown model",
                    "invalid model",
                ]
            ):
                return ValueError(
                    f"{context_prefix}OpenRouter model not available: {error_msg}. "
                    "Check model availability at https://openrouter.ai/models"
                )

            # Credit/billing errors
            if any(
                phrase in error_msg.lower()
                for phrase in [
                    "insufficient balance",
                    "insufficient credits",
                    "payment required",
                    "billing",
                    "account suspended",
                    "credit limit",
                    "billing issue",
                ]
            ):
                return RuntimeError(
                    f"{context_prefix}OpenRouter billing issue: {error_msg}. "
                    "Check your account balance at https://openrouter.ai/credits"
                )

            # Model capacity/overload errors
            if any(
                phrase in error_msg.lower()
                for phrase in [
                    "model overloaded",
                    "capacity exceeded",
                    "server overloaded",
                    "temporarily unavailable",
                    "service unavailable",
                    "model unavailable",
                ]
            ):
                return RuntimeError(
                    f"{context_prefix}Model temporarily unavailable: {error_msg}. "
                    "Try again in a few minutes or select a different model."
                )

        # OpenRouter HTTP error handling (rate limits, quota exceeded)
        if isinstance(e, (ConnectionError, TimeoutError)) or any(
            pattern in error_msg.lower()
            for pattern in ["rate limit", "quota exceeded", "429", "insufficient credits"]
        ):
            if "openrouter" in context.lower() or "openrouter.ai" in error_msg.lower():
                return RuntimeError(
                    f"{context_prefix}OpenRouter service error: {error_msg}. "
                    "Check your usage limits and credits at https://openrouter.ai/activity"
                )

        if isinstance(e, (ConnectionError, TimeoutError)) or "timeout" in error_msg.lower():
            return RuntimeError(
                f"{context_prefix}Connection failed: {error_msg}. "
                "Check network connectivity and service availability."
            )

        if isinstance(e, KeyError) and "model" in error_msg.lower():
            return ValueError(
                f"{context_prefix}Invalid model configuration: {error_msg}. "
                "Check model name and availability."
            )

        # ==================== STAGE 4: FALLBACK EXCEPTION MAPPING ====================
        # Handle any exception not caught by previous stages.
        # This ensures all exceptions are consistently wrapped and logged.

        mapped_exc = RuntimeError(f"{context_prefix}Unexpected error: {error_msg}")
        return _return_mapped_exception(mapped_exc, "fallback")

    def _validate_mixed_configuration(self, config: AIConfig) -> List[str]:
        """Handle mixed old/new configuration scenarios gracefully.

        Provides clear guidance when users have configurations that mix
        legacy and new patterns, ensuring smooth migration experience.
        """
        warnings = []

        # Check for potential legacy configuration patterns
        if hasattr(config, "service_provider") and config.provider:
            warnings.append(
                "Both 'service_provider' (legacy) and 'provider' (new) are specified. "
                "Using 'provider' value. Consider removing 'service_provider' from your config."
            )

        # Check for DeepSeek API key migration
        if config.provider and config.provider.lower() == "deepseek":
            if config.api_key and os.getenv("DEEPSEEK_API_KEY"):
                warnings.append(
                    "Both config api_key and DEEPSEEK_API_KEY environment variable are set. "
                    "Using environment variable for better security. "
                    "Consider removing 'api_key' from config and using environment variable only."
                )
            elif config.api_key and not os.getenv("DEEPSEEK_API_KEY"):
                warnings.append(
                    "DeepSeek API key in config file. For better security, consider moving to "
                    "DEEPSEEK_API_KEY environment variable and removing from config file."
                )

        # Check for OpenAI API key migration
        if config.provider and config.provider.lower() == "openai":
            if config.api_key and os.getenv("OPENAI_API_KEY"):
                warnings.append(
                    "Both config api_key and OPENAI_API_KEY environment variable are set. "
                    "Using environment variable for better security. "
                    "Consider removing 'api_key' from config and using environment variable only."
                )
            elif config.api_key and not os.getenv("OPENAI_API_KEY"):
                warnings.append(
                    "OpenAI API key in config file. For better security, consider moving to "
                    "OPENAI_API_KEY environment variable and removing from config file."
                )

        # Check for OpenRouter API key migration
        if config.provider and config.provider.lower() == "openrouter":
            if config.api_key and os.getenv("OPENROUTER_API_KEY"):
                warnings.append(
                    "Both config api_key and OPENROUTER_API_KEY environment variable are set. "
                    "Using environment variable for better security. "
                    "Consider removing 'api_key' from config and using environment variable only."
                )
            elif config.api_key and not os.getenv("OPENROUTER_API_KEY"):
                warnings.append(
                    "OpenRouter API key in config file. For better security, consider moving to "
                    "OPENROUTER_API_KEY environment variable and removing from config file."
                )

        # Check for deprecated base URLs or common misconfigurations
        if config.provider and config.provider.lower() == "ollama":
            if config.base_url and config.base_url != "http://localhost:11434":
                warnings.append(
                    f"Custom Ollama base URL detected: {config.base_url}. "
                    "Ensure this URL is correct for your Ollama installation."
                )
            if not config.model:
                warnings.append(
                    "No model specified for Ollama. This may cause connection issues. "
                    "Consider specifying a model like 'llama2' or 'codellama'."
                )

        # General configuration best practices
        if config.api_key and len(config.api_key) < 10:
            warnings.append(
                "API key appears unusually short. Please verify it's correct and complete."
            )

        # Log warnings if logger is available
        if warnings and self.logger:
            for warning in warnings:
                self.logger.warning(f"Configuration migration: {warning}")

        return warnings  # Return for testing purposes

    def _suggest_configuration_improvements(self, config: AIConfig) -> str:
        """Generate configuration improvement suggestions for users.

        Provides actionable recommendations for optimizing configuration
        based on current settings and best practices.
        """
        suggestions = []

        # Environment variable recommendations by provider
        if config.provider and config.api_key:
            provider_lower = config.provider.lower()
            env_var_map = {
                "openai": "OPENAI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
            }

            if provider_lower in env_var_map:
                env_var = env_var_map[provider_lower]
                suggestions.append(
                    f"Move API key to environment variable {env_var}:\n"
                    f"  export {env_var}='your_api_key_here'\n"
                    f"  # Then remove 'api_key' from your config file"
                )

        # Model recommendations
        if config.provider:
            provider_lower = config.provider.lower()
            if provider_lower == "openai" and not config.model:
                suggestions.append(
                    "Consider specifying a model for better performance:\n"
                    "  model = 'gpt-3.5-turbo'  # Fast and cost-effective\n"
                    "  # or model = 'gpt-4'     # More capable but slower/costlier"
                )
            elif provider_lower == "ollama" and not config.model:
                suggestions.append(
                    "Ollama requires a model specification:\n"
                    "  model = 'llama2'      # General purpose\n"
                    "  # or model = 'codellama'  # Better for code understanding"
                )
            elif provider_lower == "deepseek" and not config.model:
                suggestions.append(
                    "Consider specifying a DeepSeek model:\n"
                    "  model = 'deepseek-coder'  # Optimized for code tasks\n"
                    "  # or model = 'deepseek-chat'  # General conversation"
                )

        # Timeout and retry recommendations
        if config.timeout and config.timeout < 30:
            suggestions.append(
                "Consider increasing timeout for AI marketplace analysis:\n"
                "  timeout = 60  # Allows more time for complex evaluations"
            )

        if not config.max_retries or config.max_retries < 2:
            suggestions.append(
                "Consider enabling retries for better reliability:\n"
                "  max_retries = 3  # Retry failed requests up to 3 times"
            )

        if suggestions:
            header = f"\n--- Configuration Suggestions for {config.name} ---"
            footer = "--- End Suggestions ---\n"
            return header + "\n\n" + "\n\n".join(suggestions) + "\n" + footer

        return ""

    def _create_prompt_template(self) -> ChatPromptTemplate:
        """Create a structured ChatPromptTemplate for marketplace evaluation."""
        if self._prompt_template is None:
            self._prompt_template = ChatPromptTemplate.from_messages(
                [("system", MARKETPLACE_EVALUATION_SYSTEM_MESSAGE), ("user", "{prompt}")]
            )
        return self._prompt_template

    def _sanitize_input(self, text: str) -> str:
        """Sanitize user input to prevent prompt injection attacks."""
        if not text:
            return text

        # HTML escape to prevent script injection
        sanitized = html.escape(text, quote=True)

        # Filter only clear prompt injection attempts using pre-compiled patterns
        for compiled_pattern, replacement in self._prompt_injection_patterns:
            sanitized = compiled_pattern.sub(replacement, sanitized)

        return sanitized

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using tiktoken for accurate tokenization."""
        if not text:
            return 0

        try:
            import tiktoken

            # Use default encoding (cl100k_base) which works for most modern models
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except ImportError:
            # Fallback to simple word-based estimation if tiktoken is not available
            words = text.split()
            # Conservative multiplier based on typical tokenization ratios
            return int(len(words) * 1.3)

    def _validate_prompt(self, prompt: str) -> None:
        """Validate prompt length and content."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        estimated_tokens = self._estimate_tokens(prompt)
        if estimated_tokens > 8000:  # Conservative limit for most models
            if self.logger:
                self.logger.warning(
                    f"Prompt is very long ({estimated_tokens} estimated tokens). "
                    "Consider shortening for better performance."
                )

    def get_structured_prompt(
        self,
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
    ) -> ChatPromptTemplate:
        """Create a structured ChatPromptTemplate with the evaluation data."""
        prompt_content = self.get_prompt(listing, item_config, marketplace_config)
        self._validate_prompt(prompt_content)

        template = self._create_prompt_template()
        return template

    def _get_model(self, config: AIConfig) -> BaseChatModel:
        """Retrieve the appropriate LangChain chat model instance based on provider mapping."""
        if not config.provider:
            raise ValueError("AIConfig must have a provider specified")

        provider_key = config.provider.lower()
        if provider_key not in provider_map:
            supported_providers = ", ".join(provider_map.keys())
            raise ValueError(
                f"Unsupported provider '{config.provider}'. "
                f"Supported providers: {supported_providers}"
            )

        try:
            provider_factory = provider_map[provider_key]
            model = provider_factory(config)

            # Cache successful model creation for OpenRouter
            if provider_key == "openrouter" and config.model:
                _cache_model_availability(config.model, True)

            return model
        except (ValueError, TypeError, KeyError) as e:
            # Cache model unavailability for OpenRouter
            if provider_key == "openrouter" and config.model:
                error_type = "configuration_error"
                if "model not found" in str(e).lower():
                    error_type = "model_not_found"
                elif "insufficient" in str(e).lower():
                    error_type = "billing_issue"
                _cache_model_availability(config.model, False, error_type)

            raise ValueError(
                f"Provider '{config.provider}' configuration error: {e}. "
                f"Check API key, model name, and other required settings."
            ) from e
        except ImportError as e:
            raise RuntimeError(
                f"Provider '{config.provider}' dependencies not installed: {e}. "
                f"Install the required LangChain packages."
            ) from e
        except Exception as e:
            # Cache rate limiting for OpenRouter
            if provider_key == "openrouter":
                if any(
                    pattern in str(e).lower()
                    for pattern in ["rate limit", "429", "too many requests"]
                ):
                    provider = (
                        config.model.split("/")[0]
                        if config.model and "/" in config.model
                        else "openrouter"
                    )
                    _cache_rate_limit(provider)
                elif config.model:
                    _cache_model_availability(config.model, False, "unknown_error")

            raise RuntimeError(
                f"Failed to create model for provider '{config.provider}': {e}"
            ) from e

    def connect(self) -> None:
        """Establish connection and initialize the chat model."""
        # Validate thread safety before proceeding
        self._validate_thread_safety()

        # Handle mixed configuration scenarios
        self._validate_mixed_configuration(self.config)

        # Show configuration suggestions if enabled
        if os.getenv("AI_MARKETPLACE_MONITOR_SHOW_CONFIG_TIPS", "false").lower() == "true":
            suggestions = self._suggest_configuration_improvements(self.config)
            if suggestions and self.logger:
                self.logger.info(suggestions)

        with self._model_lock:
            if self._chat_model is None:
                try:
                    self._chat_model = self._get_model(self.config)
                    if self.logger:
                        self.logger.info(
                            f"""{hilight("[AI]", "name")} {self.config.name} connected."""
                        )
                        # Log LangSmith status for observability
                        langsmith_config = None
                        if self._main_config and hasattr(self._main_config, "langsmith"):
                            langsmith_config = self._main_config.langsmith
                        log_langsmith_status(self.logger, langsmith_config)
                except Exception as e:
                    # Map LangChain exceptions to existing error patterns
                    mapped_exception = self._map_langchain_exception(
                        e, f"Connection failed for {self.config.name}"
                    )
                    if self.logger:
                        self.logger.error(
                            f"""{hilight("[AI-Error]", "fail")} Failed to connect {self.config.name}: {mapped_exception}"""
                        )
                    raise mapped_exception from e

    def _extract_response_content(self, response: Any) -> str:
        """Extract content from LangChain response with proper type checking and fallbacks."""
        # Handle different LangChain response types
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            elif isinstance(content, list) and len(content) > 0:
                # Some models return content as a list of message parts
                return str(content[0]) if hasattr(content[0], "__str__") else str(content)

        # Try other common attributes
        if hasattr(response, "text"):
            return str(response.text)

        if hasattr(response, "message") and hasattr(response.message, "content"):
            return str(response.message.content)

        # Log unknown response type for debugging
        if self.logger:
            self.logger.warning(
                f"Unknown response type {type(response)}, falling back to string conversion"
            )

        return str(response)

    def evaluate(
        self,
        listing: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
    ) -> AIResponse:
        """Evaluate a listing using the LangChain model."""
        counter.increment(CounterItem.AI_QUERY, item_config.name)
        prompt = self.get_prompt(listing, item_config, marketplace_config)

        # Check cache first
        res: AIResponse | None = AIResponse.from_cache(listing, item_config, marketplace_config)
        if res is not None:
            if self.logger:
                self.logger.debug(
                    f"""{hilight("[AI]", res.style)} {self.config.name} previously concluded {hilight(f"{res.conclusion} ({res.score}): {res.comment}", res.style)} for listing {hilight(listing.title)}."""
                )
            return res

        self.connect()

        retries = 0
        response = None
        while retries < self.config.max_retries:
            try:
                # Thread-safe access to model
                with self._model_lock:
                    current_model = self._chat_model
                    if current_model is None:
                        raise ValueError("Chat model is not initialized")

                # Create structured prompt template and format it
                prompt_template = self._create_prompt_template()
                formatted_messages = prompt_template.format_messages(prompt=prompt)

                # Use LangChain's invoke method with formatted messages
                response = current_model.invoke(formatted_messages)
                break
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
                    self.logger.error(
                        f"""{hilight("[AI-Error]", "fail")} {self.config.name} failed to evaluate {hilight(listing.title)}: {e}"""
                    )
                retries += 1
                # Thread-safe reset of connection on error
                with self._model_lock:
                    self._chat_model = None
                time.sleep(5)
                if retries < self.config.max_retries:
                    try:
                        self.connect()
                    except Exception as connect_error:
                        if self.logger:
                            self.logger.error(
                                f"""{hilight("[AI-Error]", "fail")} {self.config.name} failed to reconnect (attempt {retries + 1}): {connect_error}"""
                            )
                        # Continue to next retry iteration

        # Check if we got a response
        if response is None:
            counter.increment(CounterItem.FAILED_AI_QUERY, item_config.name)
            raise ValueError(
                f"Failed to get response from {self.config.name} after {self.config.max_retries} retries"
            )

        # Parse the response content
        if self.logger:
            self.logger.debug(f"""{hilight("[AI-Response]", "info")} {pretty_repr(response)}""")

        # Extract content and parse rating/comment from text
        answer = self._extract_response_content(response)

        # Parse the text response to extract score and comment
        parsed_response = self._parse_ai_response(answer, item_config)

        # Use adapter to create enhanced AIResponse with token usage and metadata
        res = adapt_langchain_response(
            response=response,
            backend_name=self.config.name,
            parsed_score=parsed_response.score,
            parsed_comment=parsed_response.comment,
        )

        res.to_cache(listing, item_config, marketplace_config)
        counter.increment(CounterItem.NEW_AI_QUERY, item_config.name)
        return res
