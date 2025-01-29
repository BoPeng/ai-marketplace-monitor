import os
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
        from .users import User

        for user_name, user_config in self.config["user"].items():
            User.validate(user_name, user_config)

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
        for region_name, region_config in self.config.get("region", {}).items():
            for key in region_config:
                if key not in ("name", "radius", "city_name", "search_city"):
                    raise ValueError(f"Region {region_name} has unknown config key: {key}")
            # search_city should exist, and should be a string or list of string
            if "search_city" not in region_config:
                raise ValueError(f"Region {region_name} does not have search_city.")
            if isinstance(region_config["search_city"], str):
                region_config["search_city"] = [region_config["search_city"]]
            # check if search_city is a list of strings
            if not isinstance(region_config["search_city"], list) or not all(
                isinstance(x, str) for x in region_config["search_city"]
            ):
                raise ValueError(f"Region {region_name} search_city must be a list of strings.")
            # check if radius is an integer
            if "radius" not in region_config:
                region_config["radius"] = 500
            if not isinstance(region_config["radius"], int):
                raise ValueError(f"Region {region_name} radius must be an integer.")

        # if region is specified in other section, they must exist
        for marketplace_name, marketplace_config in self.config["marketplace"].items():
            if "search_region" in marketplace_config:
                if "search_city" not in marketplace_config:
                    marketplace_config["search_city"] = []
                for region, region_config in marketplace_config["search_region"].items():
                    if "region" not in self.config or region not in self.config["region"]:
                        raise ValueError(
                            f"Region [magenta]{region}[/magenta] specified in [magenta]{marketplace_name}[/magenta] does not exist."
                        )
                    # if region is specified, expand it into search_city
                    marketplace_config["search_city"].extend(region_config["search_city"])
                    # set radius, if market_config already has radius, they should be the same
                    if (
                        "radius" in marketplace_config
                        and marketplace_config["radius"] != region_config["radius"]
                    ):
                        raise ValueError(
                            f"Region [magenta]{region}[/magenta] specified in [magenta]{marketplace_name}[/magenta]"
                            " has different radius than the one specified in the marketplace or another region. If "
                            " you are using multiple regions, please place them into region-specific items."
                        )
                    marketplace_config["radius"] = region_config["radius"]
                    # remove duplicates
                    marketplace_config["search_city"] = list(
                        set(marketplace_config["search_city"])
                    )

        # if region is specified in any of the items, do the same
        for item_name, item_config in self.config["item"].items():
            # expand region into item_config's search_city
            if "search_region" in item_config:
                if "search_city" not in item_config:
                    item_config["search_city"] = []
                for region, region_config in item_config["search_region"].items():
                    if "region" not in self.config or region not in self.config["region"]:
                        raise ValueError(
                            f"Region [magenta]{region}[/magenta] specified in [magenta]{item_name}[/magenta] does not exist."
                        )
                    # if region is specified, expand it into search_city
                    item_config["search_city"].extend(region_config["search_city"])
                    # set radius
                    if (
                        "radius" in item_config
                        and item_config["radius"] != region_config["radius"]
                    ):
                        raise ValueError(
                            f"Region [magenta]{region}[/magenta] specified in [magenta]{item_name}[/magenta]"
                            " has different radius than the one specified in the region or from another region. "
                            " If you are using multiple regions, please group them into regions with the same "
                            " radius and create separate searches."
                        )
                    item_config["radius"] = region_config["radius"]
                    # remove duplicates
                    item_config["search_city"] = list(set(item_config["search_city"]))
