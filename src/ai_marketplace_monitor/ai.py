from dataclasses import dataclass
from logging import Logger
from typing import Any, ClassVar, Dict, Type

from openai import OpenAI  # type: ignore
from rich.pretty import pretty_repr

from .item import SearchedItem
from .marketplace import TItemConfig
from .utils import DataClassWithHandleFunc


@dataclass
class AIConfig(DataClassWithHandleFunc):
    # this argument is required
    api_key: str
    model: str | None = None
    base_url: str | None = None

    def handle_api_key(self: "AIConfig") -> None:
        if not self.api_key:
            raise ValueError("AIConfig requires an non-empty api_key.")
        self.api_key = self.api_key.strip()


class AIBackend:
    name = "unspecified"
    allowed_config_keys: ClassVar = []
    required_config_keys: ClassVar = []

    def __init__(self: "AIBackend", config: AIConfig, logger: Logger) -> None:
        self.config = config
        self.logger = logger
        self.client: OpenAI | None = None

    @classmethod
    def get_config(cls: Type["AIBackend"], **kwargs: Dict[str, Any]) -> AIConfig:
        config = AIConfig.from_dict(kwargs)
        return config

    def connect(self: "AIBackend") -> None:
        raise NotImplementedError("Connect method must be implemented by subclasses.")

    def get_prompt(
        self: "AIBackend", listing: SearchedItem, item_name: str, item_config: TItemConfig
    ) -> str:
        prompt = f"""A user would like to buy a {item_name} from facebook marketplace.
            He used keywords "{'" and "'.join(item_config.keywords)}" to perform the search."""
        if item_config.description:
            prompt += f""" He also added description "{item_config.description}" to describe the item he is interested in."""
        #
        max_price = item_config.max_price or 0
        min_price = item_config.min_price or 0
        if max_price and min_price:
            prompt += f""" He also set a price range from {min_price} to {max_price}."""
        elif max_price:
            prompt += f""" He also set a maximum price of {max_price}."""
        elif min_price:
            prompt += f""" He also set a minimum price of {min_price}."""
        #
        if item_config.exclude_keywords:
            prompt += f""" He also excluded items with keywords "{'" and "'.join(item_config.exclude_keywords)}"."""
        if item_config.exclude_by_description:
            prompt += f""" He also would like to exclude any items with description matching words "{'" and "'.join(item_config.exclude_by_description)}"."""
        #
        prompt += """Now the user has found an item that roughly matches the search criteria. """
        prompt += f"""The item is listed under title "{listing.title}", has a price of {listing.price},
            It is listed as being sold at {listing.location}, and has the following description
            "{listing.description}"\n."""
        prompt += f"""The item is posted at {listing.post_url}.\n"""
        if listing.image:
            prompt += f"""The item has an image url of {listing.image}\n"""
        prompt += """Please confirm if the item likely matches what the users would like to buy.
            Please answer only with yes or no."""
        self.logger.debug(f"Prompt: {prompt}")
        return prompt

    def confirm(
        self: "AIBackend", listing: SearchedItem, item_name: str, item_config: TItemConfig
    ) -> bool:
        raise NotImplementedError("Confirm method must be implemented by subclasses.")


class OpenAIBackend(AIBackend):
    name = "OpenAI"
    default_model = "gpt-4o"
    # the default is f"https://api.openai.com/v1"
    base_url: str | None = None

    def connect(self: "OpenAIBackend") -> None:
        if self.client is None:
            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url or self.base_url,
                timeout=10,
            )

    def confirm(
        self: "OpenAIBackend", listing: SearchedItem, item_name: str, item_config: TItemConfig
    ) -> bool:
        # ask openai to confirm the item is correct
        prompt = self.get_prompt(listing, item_name, item_config)

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
        self.logger.debug(f"Response: {pretty_repr(response)}")

        answer = response.choices[0].message.content
        res = True if answer is None else (not answer.lower().strip().startswith("no"))
        self.logger.info(
            f"""{self.name} concludes that listing [magenta]{listing.title}[/magenta] [green]matches[/green] your search criteria."""
            if res
            else f"""{self.name} concludes that listing [magenta]{listing.title}[/magenta] [red]does not match[/red] your search criteria."""
        )
        return res


class DeepSeekBackend(OpenAIBackend):
    name = "DeepSeek"
    default_model = "deepseek-chat"
    base_url = "https://api.deepseek.com"
