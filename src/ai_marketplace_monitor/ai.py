from logging import Logger
from typing import Any, ClassVar, Dict

from openai import OpenAI


class AIBackend:
    allowed_config_keys: ClassVar = []
    required_config_keys: ClassVar = []

    client: ClassVar = None

    def __init__(self, config: Dict[str, Any], logger: Logger):
        self.config = config
        self.logger = logger

    def connect(self):
        raise NotImplementedError("Connect method must be implemented by subclasses.")

    @classmethod
    def validate(cls, config: Dict[str, Any]) -> None:
        # if there are other keys in config, raise an error
        for key in config:
            if key not in cls.allowed_config_keys:
                raise ValueError(f"AI contains an invalid key {key}.")
        # make sure required key is present
        for key in cls.required_config_keys:
            if key not in config:
                raise ValueError(f"AI is missing required key {key}.")
        # make sure all required keys are not empty
        for key in cls.required_config_keys:
            if not config[key]:
                raise ValueError(f"AI key {key} is empty.")

    def confirm(self, item, item_name, item_config):
        raise NotImplementedError("Confirm method must be implemented by subclasses.")


class OpenAIBackend(AIBackend):
    allowed_config_keys: ClassVar = ["api_key", "model"]
    required_config_keys: ClassVar = ["api_key"]

    def connect(self):
        if self.client is not None:
            return self.client
        self.client = OpenAI(api_key=self.config["api_key"])
        return self

    def confirm(self, item, item_name, item_config):
        # ask openai to confirm the item is correct
        prompt = f"""A user would like to buy a {item_name} from facebook marketplace.
            He used keywords "{'" and "'.join(item_config["keywords"])}" to perform the search."""
        if "description" in item_config:
            prompt += f""" He also added description "{item_config["description"]}" to describe the item he is interested in."""
        #
        max_price = item_config.get("max_price", 0)
        min_price = item_config.get("min_price", 0)
        if max_price and min_price:
            prompt += f""" He also set a price range from {min_price} to {max_price}."""
        elif max_price:
            prompt += f""" He also set a maximum price of {max_price}."""
        elif min_price:
            prompt += f""" He also set a minimum price of {min_price}."""
        #
        if "exclude_keywords" in item_config:
            prompt += f""" He also excluded items with keywords "{'" and "'.join(item_config["exclude_keywords"])}"."""
        if "exclude_by_description" in item_config:
            prompt += f""" He also would like to exclude any items with description matching words "{'" and "'.join(item_config["exclude_by_description"])}"."""
        #
        prompt += """Now the user has found an item that roughly matches the saearch criteria. """
        prompt += f"""The item is listed under title "{item['title']}", has a price of {item['price']},
            It is listed as being sold at {item['location']}, and has the following description
            "{item['description']}"\n."""
        prompt += f"""The item is posted at {item['post_url']}.\n"""
        if "image" in item:
            prompt += f"""The item has an image url of {item['image']}\n"""
        prompt += """Please confirm if the item likely matches what the users would like to buy.
            Please answer only with yes or no."""
        self.logger.debug(f"Prompt: {prompt}")
        assert self.config is not None
        response = self.client.chat.completions.create(
            model=self.config.get("model", "gpt-4o"),
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
        self.logger.debug(f"Response: {response}")
        answer = response.choices[0].message.content
        return True if answer is None else answer.lower().strip().startswith("yes")
