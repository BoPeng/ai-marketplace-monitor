import sys
from logging import Logger
from typing import List

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .utils import merge_dicts


class Config:
    def __init__(self, config_files: List[str], logger: Logger):
        configs = []
        for config_file in config_files:
            try:
                logger.info(f"Loading config file {config_file}")
                with open(config_file, "rb") as f:
                    configs.append(tomllib.load(f))
            except tomllib.TOMLDecodeError as e:
                raise ValueError(f"Error parsing config file {config_file}: {e}") from e
        #
        # merge the list of configs into a single dictionary, including dictionaries in the values
        self.config = merge_dicts(configs)
        self.validate()

    def validate(self) -> None:
        self.validate_sections()
        self.validate_marketplaces()
        self.validate_search_items()
        self.validate_users()

    def validate_sections(self) -> None:
        # check for required sections
        for required_section in ["marketplace", "user", "item"]:
            if required_section not in self.config:
                raise ValueError(f"Config file does not contain a {required_section} section.")

    def validate_marketplaces(self) -> None:
        # check for required fields in each marketplace
        from .ai_marketplace_monitor import supported_marketplaces

        for marketplace_name, marketplace_config in self.config["marketplace"].items():
            if marketplace_name not in supported_marketplaces:
                raise ValueError(
                    f"Marketplace [magenta]{marketplace_name}[magenta] is not supported. Supported marketplaces are: {supported_marketplaces.keys()}"
                )
            marketplace_class = supported_marketplaces[marketplace_name]
            marketplace_class.validate(marketplace_config)

    def validate_search_items(self) -> None:
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
                    "marketplace",
                    "notify",
                    "exclude_keywords",
                    "exclude_sellers",
                    "min_price",
                    "max_price",
                    "exclude_by_description",
                ]:
                    raise ValueError(
                        f"Item [magenta]{item_name}[magenta] contains an invalid key {key}."
                    )

    def validate_users(self) -> None:
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
