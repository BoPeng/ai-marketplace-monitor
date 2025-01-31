import os
import sys
from logging import Logger
from typing import List

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .region import RegionConfig
from .utils import merge_dicts


class Config:

    def __init__(self: "Config", config_files: List[str], logger: Logger | None = None) -> None:
        configs = []
        system_config = os.path.join(os.path.split(__file__)[0], "config.toml")

        for config_file in [system_config, *config_files]:
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
        self.expand_regions()

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

            for key, value in self.config["ai"].items():
                if key not in supported_ai_backends:
                    raise ValueError(
                        f"Config file contains an unsupported AI backend {key} in the ai section."
                    )
                backend_class = supported_ai_backends[key]
                self.config["ai"][key] = backend_class.get_config(**value)

        # check allowed keys in config
        for key in self.config:
            if key not in ("marketplace", "user", "item", "ai", "region"):
                raise ValueError(f"Config file contains an invalid section {key}.")

    def validate_marketplaces(self: "Config") -> None:
        # check for required fields in each marketplace
        from .monitor import supported_marketplaces

        for marketplace_name, marketplace_config in self.config["marketplace"].items():
            if marketplace_name not in supported_marketplaces:
                raise ValueError(
                    f"Marketplace [magenta]{marketplace_name}[/magenta] is not supported. Supported marketplaces are: {supported_marketplaces.keys()}"
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
                        f"Item [magenta]{item_name}[/magenta] specifies a marketplace that does not exist."
                    )

            if "keywords" not in item_config:
                raise ValueError(
                    f"Item [magenta]{item_name}[/magenta] does not contain a keywords to search."
                )
            #
            if isinstance(item_config["keywords"], str):
                item_config["keywords"] = [item_config["keywords"]]
            #
            if not isinstance(item_config["keywords"], list) or not all(
                isinstance(x, str) for x in item_config["keywords"]
            ):
                raise ValueError(f"Item [magenta]{item_name}[/magenta] keywords must be a list.")
            if len(item_config["keywords"]) == 0:
                raise ValueError(f"Item [magenta]{item_name}[/magenta] keywords list is empty.")

            # description, if provided, should be a single string
            if "description" in item_config:
                if not isinstance(item_config["description"], str):
                    raise ValueError(
                        f"Item [magenta]{item_name}[/magenta] description must be a string."
                    )

            # exclude_by_description should be a list of strings
            if "exclude_by_description" in item_config:
                if isinstance(item_config["exclude_by_description"], str):
                    item_config["exclude_by_description"] = [item_config["exclude_by_description"]]
                if not isinstance(item_config["exclude_by_description"], list) or not all(
                    isinstance(x, str) for x in item_config["exclude_by_description"]
                ):
                    raise ValueError(
                        f"Item [magenta]{item_name}[/magenta] exclude_by_description must be a list."
                    )
            # if enable is set, if must be true or false (boolean)
            if "enabled" in item_config:
                if not isinstance(item_config["enabled"], bool):
                    raise ValueError(
                        f"Item [magenta]{item_name}[/magenta] enabled must be a boolean."
                    )

            item_specific_config_key = {
                "description",
                "enabled",
                "exclude_by_description",
                "exclude_keywords",
                "keywords",
                "marketplace",
            }
            from .monitor import supported_marketplaces

            for marketplace_name in self.config["marketplace"]:
                marketplace_class = supported_marketplaces[marketplace_name]
                if (
                    "marketplace" not in item_config
                    or item_config["marketplace"] == marketplace_name
                ):
                    marketplace_class.validate_shared_options(item_config)
                    #
                    for key in item_config:
                        if (
                            key
                            not in marketplace_class.marketplace_item_config_keys
                            | item_specific_config_key
                        ):
                            raise ValueError(f"Item {item_name} has unknown config key: {key}")

    def validate_users(self: "Config") -> None:
        # check for required fields in each user
        from .user import User

        for user_name, user_config in self.config["user"].items():
            self.config["user"][user_name] = User.get_config(**user_config)

        # if user is specified in other section, they must exist
        for marketplace_name, marketplace_config in self.config["marketplace"].items():
            if "notify" in marketplace_config:
                if isinstance(marketplace_config["notify"], str):
                    marketplace_config["notify"] = [marketplace_config["notify"]]
                for user in marketplace_config["notify"]:
                    if user not in self.config["user"]:
                        raise ValueError(
                            f"User [magenta]{user}[/magenta] specified in [magenta]{marketplace_name}[/magenta] does not exist."
                        )

        # if user is specified for any search item, they must exist
        for item_name, item_config in self.config["item"].items():
            if "notify" in item_config:
                if isinstance(item_config["notify"], str):
                    item_config["notify"] = [item_config["notify"]]
                for user in item_config["notify"]:
                    if user not in self.config["user"]:
                        raise ValueError(
                            f"User [magenta]{user}[/magenta] specified in [magenta]{item_name}[/magenta] does not exist."
                        )

    def expand_regions(self: "Config") -> None:
        # check for required fields in each user
        for region_name, region_config_vals in self.config.get("region", {}).items():
            self.config["region"][region_name] = RegionConfig.from_dict(region_config_vals)

        # if region is specified in other section, they must exist
        for marketplace_name, marketplace_config in self.config["marketplace"].items():
            if "search_region" in marketplace_config:
                marketplace_config["search_city"] = []
                marketplace_config["radius"] = []

                for region in marketplace_config["search_region"]:
                    region_config: RegionConfig = self.config["region"][region]
                    if "region" not in self.config or region not in self.config["region"]:
                        raise ValueError(
                            f"Region [magenta]{region}[/magenta] specified in [magenta]{marketplace_name}[/magenta] does not exist."
                        )
                    # if region is specified, expand it into search_city
                    marketplace_config["search_city"].extend(region_config.search_city)
                    # set radius, if market_config already has radius, they should be the same

                    marketplace_config["radius"].extend(region_config.radius)
                    # remove duplicates
                    marketplace_config["search_city"].extend(
                        list(set(marketplace_config["search_city"]))
                    )

        # if region is specified in any of the items, do the same
        for item_name, item_config in self.config["item"].items():
            # expand region into item_config's search_city
            if "search_region" in item_config:
                item_config["search_city"] = []
                item_config["radius"] = []
                for region in item_config["search_region"]:
                    region_config = self.config["region"][region]
                    if "region" not in self.config or region not in self.config["region"]:
                        raise ValueError(
                            f"Region [magenta]{region}[/magenta] specified in [magenta]{item_name}[/magenta] does not exist."
                        )
                    # if region is specified, expand it into search_city
                    item_config["search_city"].extend(region_config.search_city)
                    #
                    item_config["radius"].extend(region_config.radius)
                    item_config["search_city"].extend(list(set(item_config["search_city"])))
