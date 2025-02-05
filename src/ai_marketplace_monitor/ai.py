import re
import time
from dataclasses import dataclass, field
from enum import Enum
from logging import Logger
from typing import Any, ClassVar, Generic, Type, TypeVar

from openai import OpenAI  # type: ignore
from rich.pretty import pretty_repr

from .item import SearchedItem
from .marketplace import TItemConfig
from .utils import CacheType, DataClassWithHandleFunc, cache, hilight


class AIServiceProvider(Enum):
    OPENAI = "OpenAI"
    DEEPSEEK = "DeepSeek"
    OLLAMA = "Ollama"


@dataclass
class AIResponse:
    score: int
    comment: str

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
        if self.score < 3:
            return "fail"
        if self.score > 3:
            return "succ"
        return "name"


@dataclass
class AIConfig(DataClassWithHandleFunc):
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

    def get_prompt(self: "AIBackend", listing: SearchedItem, item_config: TItemConfig) -> str:
        prompt = (
            f"""A user would like to buy a {item_config.name} from facebook marketplace. """
            f"""He used keywords "{'" and "'.join(item_config.keywords)}" to perform the search. """
        )
        if item_config.description:
            prompt += f"""He also added description "{item_config.description}" to describe the item he is interested in. """
        #
        max_price = item_config.max_price or 0
        min_price = item_config.min_price or 0
        if max_price and min_price:
            prompt += f"""He also set a price range from {min_price} to {max_price}. """
        elif max_price:
            prompt += f"""He also set a maximum price of {max_price}. """
        elif min_price:
            prompt += f"""He also set a minimum price of {min_price}. """
        #
        if item_config.exclude_keywords:
            prompt += f"""He also excluded items with keywords "{'" and "'.join(item_config.exclude_keywords)}"."""
        if item_config.exclude_by_description:
            prompt += f"""He also would like to exclude any items with description matching words "{'" and "'.join(item_config.exclude_by_description)}"."""
        #
        prompt += (
            """\n\nNow the user has found an listing that roughly matches the search criteria. """
            f"""The listing is listed under title "{listing.title}", with {listing.condition} condition, """
            f"""has a price of {listing.price} with seller from {listing.location}, """
            f"""The listing is posted at {listing.post_url} with description "{listing.description}"\n\n"""
            "Given all these information, please evaluate if this listing matches what the user "
            "has in mind. Please consider the description, any extended knowledge you might have "
            "(such as the MSRP and model year of the products), condition, the sincerity of the "
            "seller, and give me a recommendation in the format of a rating. \n"
            "Rating 1, unmatched: the item does not match at all, for example, is a product in a different category, and the user should not consider.\n"
            "Rating 2, unknown: there is not enough information to make a good judgement. the user can choose to ignore or try to contact the seller for more clarification.\n"
            "Rating 3, poor match: the item is acceptable but not a good match, which can be due to higher than average price, item condition, or poor description from the seller.\n"
            "Rating 4, good match: the item is a potential good deal and you recommend the user to contact the seller.\n"
            "Rating 5, good deal: the item is a very good deal, with good condition and very competitive price. The user should try to grab it as soon as he can.\n"
            "Please return the answer starting with word 'Rating:' and a rating as a number from 1 to 5, a new line, then a summary about why you make this recommendation. "
            "The summary should be brief and no more than 30 words."
        )
        if self.logger:
            self.logger.debug(f"""{hilight("[AI-Prompt]", "info")} {prompt}""")
        return prompt

    def evaluate(self: "AIBackend", listing: SearchedItem, item_config: TItemConfig) -> AIResponse:
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
            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url or self.base_url,
                timeout=self.config.timeout,
            )
            if self.logger:
                self.logger.info(f"""{hilight("[AI]", "name")} {self.config.name} connected.""")

    def evaluate(
        self: "OpenAIBackend", listing: SearchedItem, item_config: TItemConfig
    ) -> AIResponse:
        # ask openai to confirm the item is correct
        prompt = self.get_prompt(listing, item_config)
        cached_result = cache.get(
            (CacheType.AI_INQUIRY.value, listing.marketplace, item_config.name, listing.id)
        )
        if cached_result is not None:
            if self.logger:
                self.logger.info(
                    f"""{hilight("[AI]", "name")} {self.config.name} has already evaluated {hilight(listing.title)}."""
                )
            return AIResponse(cached_result["score"], cached_result["comment"])

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
        if answer is None or not answer.strip() or "Rating:" not in answer:
            raise ValueError(f"Empty or invalid response from {self.config.name}: {response}")

        if answer.strip().startswith("<think>"):
            # remove <think></think> from the output
            answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()

        #
        lines = answer.split("\n")
        # if any of the lines contains "Rating: ", extract the rating from it.
        score: str | None = None
        comment = ""
        for line in lines:
            matched = re.match(r".*Rating:?\s*([1-5])", line)
            if matched:
                score = matched.group(1)
                continue
            if score is not None:
                comment += line + "\n"
        # if no rating is find, take the first line as the rating
        if score is None:
            raise ValueError(f"Unrecognized response from {self.config.name}: {response}")

        cache.set(
            (CacheType.AI_INQUIRY.value, listing.marketplace, item_config.name, listing.id),
            {"score": int(score), "comment": comment.strip()},
            tag=CacheType.AI_INQUIRY.value,
        )
        res = AIResponse(int(score), comment.strip())

        if self.logger:
            self.logger.info(
                f"""{hilight("[AI]", res.style)} {self.config.name} concludes {hilight(f"{res.conclusion} ({res.score}): {res.comment}", res.style)} for listing {hilight(listing.title)}."""
            )
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
