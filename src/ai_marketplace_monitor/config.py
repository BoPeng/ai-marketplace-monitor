import sys
from dataclasses import dataclass, field
from enum import Enum
from itertools import chain
from logging import Logger
from pathlib import Path
from typing import Any, Dict, Generic, List

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .ai import DeepSeekBackend, OllamaBackend, OpenAIBackend, TAIConfig
from .facebook import FacebookMarketplace
from .marketplace import TItemConfig, TMarketplaceConfig
from .notification import NotificationConfig
from .region import RegionConfig
from .user import User, UserConfig
from .utils import MonitorConfig, hilight, merge_dicts

supported_marketplaces = {"facebook": FacebookMarketplace}
supported_ai_backends = {
    "deepseek": DeepSeekBackend,
    "openai": OpenAIBackend,
    "ollama": OllamaBackend,
}


class ConfigItem(Enum):
    MONITOR = "monitor"
    MARKETPLACE = "marketplace"
    USER = "user"
    ITEM = "item"
    AI = "ai"
    REGION = "region"
    NOTIFICATION = "notification"


@dataclass
class Config(Generic[TAIConfig, TItemConfig, TMarketplaceConfig]):
    monitor: MonitorConfig = field(init=False)
    ai: Dict[str, TAIConfig] = field(init=False)
    user: Dict[str, UserConfig] = field(init=False)
    notification: Dict[str, NotificationConfig] = field(init=False)
    marketplace: Dict[str, TMarketplaceConfig] = field(init=False)
    item: Dict[str, TItemConfig] = field(init=False)
    region: Dict[str, RegionConfig] = field(init=False)

    def __init__(self: "Config", config_files: List[Path], logger: Logger | None = None) -> None:
        configs = []
        system_config = Path(__file__).parent / "config.toml"

        for config_file in [system_config, *config_files]:
            try:
                if logger:
                    logger.debug(
                        f"""{hilight("[Monitor]", "succ")} config file {hilight(str(config_file))}"""
                    )
                with open(config_file, "rb") as f:
                    configs.append(tomllib.load(f))
            except tomllib.TOMLDecodeError as e:
                raise ValueError(f"Error parsing config file {config_file}: {e}") from e
        #
        # merge the list of configs into a single dictionary, including dictionaries in the values
        config = merge_dicts(configs)

        self.validate_sections(config)
        self.get_monitor_config(config)
        self.get_ai_config(config)
        self.get_notification_config(config)
        self.get_marketplace_config(config)
        self.get_user_config(config)
        self.get_region_config(config)
        self.get_item_config(config)
        self.validate_users()
        self.validate_ais()
        self.expand_notifications(logger)
        self.expand_regions()

    def get_monitor_config(self: "Config", config: Dict[str, Any]) -> None:
        self.monitor = MonitorConfig(name="monitor", **config.get("global", {}))

    def get_ai_config(self: "Config", config: Dict[str, Any]) -> None:
        # convert ai config to AIConfig objects
        if not isinstance(config.get("ai", {}), dict):
            raise ValueError("ai section must be a dictionary.")

        self.ai = {}
        for key, value in config.get("ai", {}).items():
            try:
                backend_class = supported_ai_backends[value.get("provider", key).lower()]
            except KeyboardInterrupt:
                raise
            except Exception as e:
                raise ValueError(
                    f"Config file contains an unsupported AI backend {key} in the ai section."
                ) from e
            self.ai[key] = backend_class.get_config(name=key, **value)

    def get_notification_config(self: "Config", config: Dict[str, Any]) -> None:
        if not isinstance(config.get("notification", {}), dict):
            raise ValueError("notification section must be a dictionary.")

        self.notification: Dict[str, NotificationConfig] = {}
        for key, value in config.get("notification", {}).items():
            cfg = NotificationConfig.get_config(name=key, **value)
            if cfg is None:
                raise ValueError(
                    f"Unable to determine notification type for notification section {key}"
                )
            else:
                self.notification[key] = cfg

    def get_marketplace_config(self: "Config", config: Dict[str, Any]) -> None:
        # check for required fields in each marketplace
        self.marketplace = {}
        for marketplace_name, marketplace_config in config["marketplace"].items():
            market_type = marketplace_config.get("market_type", "facebook")
            if market_type not in supported_marketplaces:
                raise ValueError(
                    f"Marketplace {hilight(market_type)} is not supported. Supported marketplaces are: {supported_marketplaces.keys()}"
                )
            marketplace_class = supported_marketplaces[market_type]
            self.marketplace[marketplace_name] = marketplace_class.get_config(
                name=marketplace_name, **marketplace_config
            )

    def get_user_config(self: "Config", config: Dict[str, Any]) -> None:
        # check for required fields in each user
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
                        f"Item {hilight(item_name)} specifies a marketplace that does not exist."
                    )

            for marketplace_name, markerplace_config in config["marketplace"].items():
                marketplace_class = supported_marketplaces[
                    markerplace_config.get("market_type", "facebook")
                ]
                if (
                    "marketplace" not in item_config
                    or item_config["marketplace"] == marketplace_name
                ):
                    # use the first available marketplace
                    self.item[item_name] = marketplace_class.get_item_config(
                        name=item_name,
                        marketplace=marketplace_name,
                        **{x: y for x, y in item_config.items() if x != "marketplace"},
                    )
                    break

    def validate_sections(self: "Config", config: Dict[str, Any]) -> None:
        # check for required sections
        for required_section in ["marketplace", "user", "item"]:
            if required_section not in config:
                raise ValueError(f"Config file does not contain a {required_section} section.")

        # check allowed keys in config
        for key in config:
            if key not in [x.value for x in ConfigItem]:
                raise ValueError(f"Config file contains an invalid section {key}.")

    def validate_users(self: "Config") -> None:
        """Check if notified users exists"""
        # if user is specified in other section, they must exist
        for config in chain(self.marketplace.values(), self.item.values()):
            for user in config.notify or []:
                if user not in self.user:
                    raise ValueError(
                        f"User {hilight(user)} specified in {hilight(config.name)} does not exist."
                    )

    def validate_ais(self: "Config") -> None:
        # if ai is specified in other section, they must exist
        for config in chain(self.marketplace.values(), self.item.values()):
            for ai in config.ai or []:
                if ai not in self.ai:
                    raise ValueError(
                        f"AI {hilight(config.ai)} specified in {hilight(config.name)} does not exist."
                    )

    def expand_notifications(self: "Config", logger: Logger | None = None) -> None:
        for config in self.user.values():
            for notification_name in (
                config.notify_with if config.notify_with is not None else self.notification.keys()
            ):
                notification_types = set()
                if notification_name not in self.notification:
                    raise ValueError(
                        f"User {hilight(config.name)} specifies an undefined notification method {notification_name}."
                    )
                notification_config = self.notification[notification_name]
                #
                if notification_config.enabled is False:
                    continue
                # add values of notification_config to user config
                if notification_config.__class__.__name__ in notification_types:
                    if logger:
                        logger.warning(
                            f"Ignore additional notification {hilight(notification_name)} with type {notification_config.__class__.__name__} for user {config.name}."
                        )
                    continue
                else:
                    notification_types.add(notification_config.__class__.__name__)

                for key, value in notification_config.__dict__.items():
                    # name is the notification name and should not override username
                    if key not in ("type", "name") and value is not None:
                        if getattr(config, key) is not None:
                            if logger:
                                logger.warning(
                                    f"Overriding {hilight(key)} for user {config.name} with value {value} from notification {hilight(notification_name)}."
                                )
                        setattr(config, key, value)

    def expand_regions(self: "Config") -> None:
        # if region is specified in other section, they must exist
        for config in chain(self.marketplace.values(), self.item.values()):
            if config.search_region is None:
                continue
            config.city_name = []
            config.search_city = []
            config.radius = []

            for region in config.search_region:
                region_config: RegionConfig = self.region[region]
                if region not in self.region:
                    raise ValueError(
                        f"Region {hilight(region)} specified in {hilight(config.name)} does not exist."
                    )
                if region_config.enabled is False:
                    continue
                # avoid duplicated addition of search_city
                for search_city, city_name, radius in zip(
                    region_config.search_city or [],
                    region_config.city_name or [],
                    region_config.radius or [],
                ):
                    if search_city not in config.search_city:
                        config.search_city.append(search_city)
                        config.city_name.append(city_name)
                        config.radius.append(radius)
