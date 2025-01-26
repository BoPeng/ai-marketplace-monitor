import sys
from logging import Logger
from typing import List

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .utils import merge_dicts


class Config:
    def __init__(self: "Config", config_files: List[str], logger: Logger | None = None) -> None:
        configs = []
        for config_file in config_files:
            try:
                if logger:
                    logger.info(f"Loading config file {config_file}")
                with open(config_file, "rb") as f:
                    configs.append(tomllib.load(f))
            except tomllib.TOMLDecodeError as e:
                raise ValueError(f"Error parsing config file {config_file}: {e}") from e
        #
        # merge the list of configs into a single dictionary, including dictionaries in the values
        self.config = merge_dicts(configs)
        self.validate()

    def validate(self: "Config") -> None:
        self.validate_sections()
        self.validate_marketplaces()
        self.validate_search_items()
        self.validate_users()

    def validate_sections(self: "Config") -> None:
        # check for required sections
        for required_section in ["marketplace", "user", "item"]:
            if required_section not in self.config:
                raise ValueError(f"Config file does not contain a {required_section} section.")

        if "ai" in self.config:
            # this section only accept a key called api-key
            if not isinstance(self.config["ai"], dict):
                raise ValueError("ai section must be a dictionary.")

            from .monitor import supported_ai_backends

            for key in self.config["ai"]:
                if key not in supported_ai_backends:
                    raise ValueError(
                        f"Config file contains an unsupported AI backend {key} in the ai section."
                    )
                else:
                    backend_class = supported_ai_backends[key]
                    backend_class.validate(self.config["ai"][key])
        else:
            self.config["ai"] = {}

        # check allowed keys in config
        for key in self.config:
            if key not in ("marketplace", "user", "item", "ai"):
                raise ValueError(f"Config file contains an invalid section {key}.")

    def validate_marketplaces(self: "Config") -> None:
        # check for required fields in each marketplace
        from .monitor import supported_marketplaces

        for marketplace_name, marketplace_config in self.config["marketplace"].items():
            if marketplace_name not in supported_marketplaces:
                raise ValueError(
                    f"Marketplace [magenta]{marketplace_name}[magenta] is not supported. Supported marketplaces are: {supported_marketplaces.keys()}"
                )
            marketplace_class = supported_marketplaces[marketplace_name]
            marketplace_class.validate(marketplace_config)

    def validate_search_items(self: "Config") -> None:
        # check for keywords in each "item" to be searched
        for item_name, item_config in self.config["item"].items():
            # if marketplace is specified, it must exist
            if "marketplace" in item_config:
                if item_config["marketplace"] not in self.config["marketplace"]:
                    raise ValueError(
                        f"Item [magenta]{item_name}[magenta] specifies a marketplace that does not exist."
                    )

            if "keywords" not in item_config:
                raise ValueError(
                    f"Item [magenta]{item_name}[magenta] does not contain a keywords to search."
                )
            #
            if isinstance(item_config["keywords"], str):
                item_config["keywords"] = [item_config["keywords"]]
            #
            if not isinstance(item_config["keywords"], list) or not all(
                isinstance(x, str) for x in item_config["keywords"]
            ):
                raise ValueError(f"Item [magenta]{item_name}[magenta] keywords must be a list.")
            if len(item_config["keywords"]) == 0:
                raise ValueError(f"Item [magenta]{item_name}[magenta] keywords list is empty.")

            # description, if provided, should be a single string
            if "description" in item_config:
                if not isinstance(item_config["description"], str):
                    raise ValueError(
                        f"Item [magenta]{item_name}[magenta] description must be a string."
                    )
            # exclude_sellers should be a list of strings
            if "exclude_sellers" in item_config:
                if isinstance(item_config["exclude_sellers"], str):
                    item_config["exclude_sellers"] = [item_config["exclude_sellers"]]
                if not isinstance(item_config["exclude_sellers"], list) or not all(
                    isinstance(x, str) for x in item_config["exclude_sellers"]
                ):
                    raise ValueError(
                        f"Item [magenta]{item_name}[magenta] exclude_sellers must be a list."
                    )
            #
            # exclude_by_description should be a list of strings
            if "exclude_by_description" in item_config:
                if isinstance(item_config["exclude_by_description"], str):
                    item_config["exclude_by_description"] = [item_config["exclude_by_description"]]
                if not isinstance(item_config["exclude_by_description"], list) or not all(
                    isinstance(x, str) for x in item_config["exclude_by_description"]
                ):
                    raise ValueError(
                        f"Item [magenta]{item_name}[magenta] exclude_by_description must be a list."
                    )
            # if enable is set, if must be true or false (boolean)
            if "enabled" in item_config:
                if not isinstance(item_config["enabled"], bool):
                    raise ValueError(
                        f"Item [magenta]{item_name}[magenta] enabled must be a boolean."
                    )

            # if there are other keys in item_config, raise an error
            for key in item_config:
                if key not in [
                    "enabled",
                    "keywords",
                    "description",
                    "marketplace",
                    "notify",
                    "exclude_keywords",
                    "exclude_sellers",
                    "min_price",
                    "max_price",
                    "search_city",
                    "exclude_by_description",
                ]:
                    raise ValueError(
                        f"Item [magenta]{item_name}[magenta] contains an invalid key {key}."
                    )

    def validate_users(self: "Config") -> None:
        # check for required fields in each user
        from .users import User

        for user_name, user_config in self.config["user"].items():
            User.validate(user_name, user_config)

        # if user is specified in other section, they must exist
        for marketplace_config in self.config["marketplace"].values():
            if "notify" in marketplace_config:
                if isinstance(marketplace_config["notify"], str):
                    marketplace_config["notify"] = [marketplace_config["notify"]]
                for user in marketplace_config["notify"]:
                    if user not in self.config["user"]:
                        raise ValueError(
                            f"User [magenta]{user}[magenta] specified in [magenta]{marketplace_config['name']}[magenta] does not exist."
                        )

        # if user is specified for any search item, they must exist
        for item_config in self.config["item"].values():
            if "notify" in item_config:
                if isinstance(item_config["notify"], str):
                    item_config["notify"] = [item_config["notify"]]
                for user in item_config["notify"]:
                    if user not in self.config["user"]:
                        raise ValueError(
                            f"User [magenta]{user}[magenta] specified in [magenta]{item_config['name']}[magenta] does not exist."
                        )
