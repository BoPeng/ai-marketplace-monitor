import os
import sys
from dataclasses import dataclass, field
from logging import Logger
from typing import Any, Dict, Generic, List

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .ai import AIConfig
from .marketplace import TItemConfig, TMarketplaceConfig
from .region import RegionConfig
from .user import UserConfig
from .utils import merge_dicts


@dataclass
class Config(Generic[TItemConfig, TMarketplaceConfig]):
    ai: Dict[str, AIConfig] = field(init=False)
    user: Dict[str, UserConfig] = field(init=False)
    marketplace: Dict[str, TMarketplaceConfig] = field(init=False)
    item: Dict[str, TItemConfig] = field(init=False)
    region: Dict[str, RegionConfig] = field(init=False)

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
        config = merge_dicts(configs)

        self.validate_sections(config)
        self.get_ai_config(config)
        self.get_marketplace_config(config)
        self.get_user_config(config)
        self.get_region_config(config)
        self.get_item_config(config)
        self.validate_users()
        self.expand_regions()

    def get_ai_config(self: "Config", config: Dict[str, Any]) -> None:
        # convert ai config to AIConfig objects
        if not isinstance(config.get("ai", {}), dict):
            raise ValueError("ai section must be a dictionary.")

        from .monitor import supported_ai_backends

        self.ai: Dict[str, AIConfig] = {}
        for key, value in config.get("ai", {}).items():
            if key not in supported_ai_backends:
                raise ValueError(
                    f"Config file contains an unsupported AI backend {key} in the ai section."
                )
            backend_class = supported_ai_backends[key]
            self.ai[key] = backend_class.get_config(name=key, **value)

    def get_marketplace_config(self: "Config", config: Dict[str, Any]) -> None:
        # check for required fields in each marketplace
        from .monitor import supported_marketplaces

        self.marketplace = {}
        for marketplace_name, marketplace_config in config["marketplace"].items():
            if marketplace_name not in supported_marketplaces:
                raise ValueError(
                    f"Marketplace [magenta]{marketplace_name}[/magenta] is not supported. Supported marketplaces are: {supported_marketplaces.keys()}"
                )
            marketplace_class = supported_marketplaces[marketplace_name]
            self.marketplace[marketplace_name] = marketplace_class.get_config(
                name=marketplace_name, **marketplace_config
            )

    def get_user_config(self: "Config", config: Dict[str, Any]) -> None:
        # check for required fields in each user
        from .user import User

        self.user: Dict[str, UserConfig] = {}
        for user_name, user_config in config["user"].items():
            self.user[user_name] = User.get_config(name=user_name, **user_config)

    def get_region_config(self: "Config", config: Dict[str, Any]) -> None:
        # check for required fields in each user
        self.region: Dict[str, RegionConfig] = {}
        for region_name, region_config in config.get("region", {}).items():
            self.region[region_name] = RegionConfig(name=region_name, **region_config)

    def get_item_config(self: "Config", config: Dict[str, Any]) -> None:
        # check for required fields in each user

        self.item = {}
        for item_name, item_config in config["item"].items():
            # if marketplace is specified, it must exist
            if "marketplace" in item_config:
                if item_config["marketplace"] not in config["marketplace"]:
                    raise ValueError(
                        f"Item [magenta]{item_name}[/magenta] specifies a marketplace that does not exist."
                    )

            from .monitor import supported_marketplaces

            for marketplace_name in config["marketplace"]:
                marketplace_class = supported_marketplaces[marketplace_name]
                if (
                    "marketplace" not in item_config
                    or item_config["marketplace"] == marketplace_name
                ):
                    self.item[item_name] = marketplace_class.get_item_config(
                        name=item_name, **item_config
                    )

    def validate_sections(self: "Config", config: Dict[str, Any]) -> None:
        # check for required sections
        for required_section in ["marketplace", "user", "item"]:
            if required_section not in config:
                raise ValueError(f"Config file does not contain a {required_section} section.")

        # check allowed keys in config
        for key in config:
            if key not in ("marketplace", "user", "item", "ai", "region"):
                raise ValueError(f"Config file contains an invalid section {key}.")

    def validate_users(self: "Config") -> None:
        # check for required fields in each user

        # if user is specified in other section, they must exist
        for marketplace_name, marketplace_config in self.marketplace.items():
            for user in marketplace_config.notify or []:
                if user not in self.user:
                    raise ValueError(
                        f"User [magenta]{user}[/magenta] specified in [magenta]{marketplace_name}[/magenta] does not exist."
                    )

        # if user is specified for any search item, they must exist
        for item_name, item_config in self.item.items():
            for user in item_config.notify or []:
                if user not in self.user:
                    raise ValueError(
                        f"User [magenta]{user}[/magenta] specified in [magenta]{item_name}[/magenta] does not exist."
                    )

    def expand_regions(self: "Config") -> None:
        # if region is specified in other section, they must exist
        for marketplace_name, marketplace_config in self.marketplace.items():
            if marketplace_config.search_region is None:
                continue

            marketplace_config.search_city = []
            marketplace_config.radius = []

            for region in marketplace_config.search_region:
                region_config: RegionConfig = self.region[region]
                if region not in self.region:
                    raise ValueError(
                        f"Region [magenta]{region}[/magenta] specified in [magenta]{marketplace_name}[/magenta] does not exist."
                    )
                # if region is specified, expand it into search_city
                marketplace_config.search_city.extend(region_config.search_city)
                # set radius, if market_config already has radius, they should be the same

                marketplace_config.radius.extend(region_config.radius)
                # remove duplicates
                marketplace_config.search_city.extend(list(set(marketplace_config.search_city)))

        # if region is specified in any of the items, do the same
        for item_name, item_config in self.item.items():
            # expand region into item_config's search_city
            if item_config.search_region is None:
                continue
            item_config.search_city = []
            item_config.radius = []
            for region in item_config.search_region:
                region_config = self.region[region]
                if region not in self.region:
                    raise ValueError(
                        f"Region [magenta]{region}[/magenta] specified in [magenta]{item_name}[/magenta] does not exist."
                    )
                # if region is specified, expand it into search_city
                item_config.search_city.extend(region_config.search_city)
                #
                item_config.radius.extend(region_config.radius)
                item_config.search_city.extend(list(set(item_config.search_city)))
