from dataclasses import dataclass
from enum import Enum
from logging import Logger
from typing import Any, ClassVar, Generic, Type, TypeVar

from openai import OpenAI  # type: ignore
from rich.pretty import pretty_repr

from .item import SearchedItem
from .marketplace import TItemConfig
from .utils import DataClassWithHandleFunc, hilight


class AIServiceProvider(Enum):
    OPENAI = "OpenAI"
    DEEPSEEK = "DeepSeek"


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

    api_key: str
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None

    def handle_provider(self: "AIConfig") -> None:
        if self.provider is None:
            return
        if self.provider.lower() not in [x.value.lower() for x in AIServiceProvider]:
            raise ValueError(
                f"""AIConfig requires a valid service provider. Valid providers are {hilight(", ".join([x.value for x in AIServiceProvider]))}"""
            )

    def handle_api_key(self: "AIConfig") -> None:
        if not self.api_key:
            raise ValueError("AIConfig requires an non-empty api_key.")
        self.api_key = self.api_key.strip()


@dataclass
class OpenAIConfig(AIConfig):
    pass


@dataclass
class DeekSeekConfig(OpenAIConfig):
    pass


TAIConfig = TypeVar("TAIConfig", bound=AIConfig)


class AIBackend(Generic[TAIConfig]):
    def __init__(self: "AIBackend", config: AIConfig, logger: Logger) -> None:
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
            f"""The listing is listed under title "{listing.title}", has a price of {listing.price} with seller from {listing.location},"""
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
            "Please return the answer in the format of the rating (a number), a colon separator, then a summary why you make this recommendation. The summary should be brief and no more than 30 words."
        )
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
                timeout=10,
            )

    def evaluate(
        self: "OpenAIBackend", listing: SearchedItem, item_config: TItemConfig
    ) -> AIResponse:
        # ask openai to confirm the item is correct
        prompt = self.get_prompt(listing, item_config)

        assert self.client is not None

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
        # check if the response is yes
        self.logger.debug(f"""{hilight("[AI-Response]", "info")} {pretty_repr(response)}""")

        answer = response.choices[0].message.content
        if (
            answer is None
            or not answer.strip()
            or not answer.strip()[0].isdigit()
            or ":" not in answer
        ):
            raise ValueError(f"Empty or invalid response from {self.config.name}")

        score, comment = answer.strip().split(":", 1)
        if int(score) > 5 or int(score) < 1:
            score = "1"
        res = AIResponse(int(score), comment.strip())

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
