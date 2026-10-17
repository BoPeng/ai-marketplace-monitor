import copy
import sys
import warnings
from dataclasses import dataclass, field
from enum import Enum
from itertools import chain
from logging import Logger
from pathlib import Path
from typing import Any, Dict, Generic, List, Tuple, Type, cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .ai import (
    AnthropicBackend,
    DeepSeekBackend,
    GeminiBackend,
    OllamaBackend,
    OpenAIBackend,
    TAIConfig,
    UnitySVCBackend,
)
from .channels import user_channels
from .marketplaces import item_marketplaces, marketplace_type, supported_marketplaces
from .marketplaces.base import (
    Marketplace,
    TItemConfig,
    TMarketplaceConfig,
    location_keys,
    location_value,
    option_names,
)
from .notification import NotificationConfig
from .region import RegionConfig
from .user import User, UserConfig
from .utils import (
    TRANSLATION_FIELDS,
    MonitorConfig,
    TranslationConfig,
    Translator,
    amm_home,
    hilight,
    merge_dicts,
)

supported_ai_backends = {
    "deepseek": DeepSeekBackend,
    "gemini": GeminiBackend,
    "openai": OpenAIBackend,
    "anthropic": AnthropicBackend,
    "ollama": OllamaBackend,
    "unitysvc": UnitySVCBackend,
}

SYSTEM_CONFIG = Path(__file__).parent / "config.toml"


def _load_toml(path: Path, logger: Logger | None = None) -> Dict[str, Any]:
    if logger:
        logger.debug(f"""{hilight("[Monitor]", "succ")} config file {hilight(str(path))}""")
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Error parsing config file {path}: {e}") from e


def resolve_config_files(config_files: List[Path] | None) -> List[Path]:
    """Config files in read order: the default file (if it exists), then each given file.

    Shared by the monitor and ``aimm configure`` so both read the same set of files.
    """
    explicit = []
    for file_path in config_files or []:
        resolved = file_path.expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Config file {resolved} not found.")
        explicit.append(resolved)
    default_config = amm_home / "config.toml"
    return ([default_config] if default_config.exists() else []) + explicit


def load_config_dicts(
    config_files: List[Path], logger: Logger | None = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (bundled system config, merged user config) as parsed, unprocessed dicts."""
    system = _load_toml(SYSTEM_CONFIG, logger)
    user = merge_dicts([_load_toml(f, logger) for f in config_files])
    return system, user


class ConfigItem(Enum):
    MONITOR = "monitor"
    MARKETPLACE = "marketplace"
    USER = "user"
    ITEM = "item"
    AI = "ai"
    REGION = "region"
    NOTIFICATION = "notification"
    TRANSLATION = "translation"


@dataclass
class Config(Generic[TAIConfig, TItemConfig, TMarketplaceConfig]):
    monitor: MonitorConfig = field(init=False)
    ai: Dict[str, TAIConfig] = field(init=False)
    user: Dict[str, UserConfig] = field(init=False)
    notification: Dict[str, NotificationConfig] = field(init=False)
    marketplace: Dict[str, TMarketplaceConfig] = field(init=False)
    # each item's config, for the first marketplace it is searched in
    item: Dict[str, TItemConfig] = field(init=False)
    # each item's config for each marketplace it is searched in: {item: {marketplace: config}}
    item_targets: Dict[str, Dict[str, TItemConfig]] = field(init=False)
    translator: Dict[str, Translator] = field(init=False)
    region: Dict[str, RegionConfig] = field(init=False)

    def __init__(self: "Config", config_files: List[Path], logger: Logger | None = None) -> None:
        system, user = load_config_dicts(config_files, logger)
        self._load(system, user, logger)

    @classmethod
    def from_dicts(
        cls: type["Config"],
        system: Dict[str, Any],
        user: Dict[str, Any],
        logger: Logger | None = None,
        *,
        partial: bool = False,
    ) -> "Config":
        """Build a Config from already-parsed dicts without mutating them.

        ``partial`` accepts a config that does not yet have every section the monitor needs
        (marketplace, user, item), as while it is being written with ``aimm configure``.
        """
        obj = cls.__new__(cls)
        obj._load(system, user, logger, partial=partial)
        return obj

    def _load(
        self: "Config",
        system: Dict[str, Any],
        user: Dict[str, Any],
        logger: Logger | None,
        *,
        partial: bool = False,
    ) -> None:
        # merge_dicts mutates nested dicts in place, so work on copies
        config = merge_dicts([copy.deepcopy(system), copy.deepcopy(user)])

        self.validate_sections(config, partial=partial)
        self.get_translator_config(config)
        self.get_monitor_config(config)
        self.get_ai_config(config)
        self.get_notification_config(config)
        self.get_marketplace_config(config)
        self.get_user_config(config)
        self.get_region_config(config)
        self.get_item_config(config, logger)
        self.validate_users()
        self.validate_ais()
        if not partial:
            self.validate_marketplaces()
        self.expand_notifications(logger)
        self.expand_regions()
        self.validate_items()

    def get_translator_config(self: "Config", config: Dict[str, Any]) -> None:
        if not isinstance(config.get("translation", {}), dict):
            raise ValueError("translation section must be a dictionary.")

        self.translator = {}
        for key, value in config.get("translation", {}).items():
            translation = TranslationConfig(
                name=key,
                dictionary={k: v for k, v in value.items() if k not in TRANSLATION_FIELDS},
                **{k: v for k, v in value.items() if k in TRANSLATION_FIELDS},
            )
            if translation.enabled is False:
                continue
            self.translator[key] = Translator(
                locale=translation.locale, dictionary=translation.dictionary
            )

    def get_monitor_config(self: "Config", config: Dict[str, Any]) -> None:
        self.monitor = MonitorConfig(name="monitor", **config.get("monitor", {}))

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
        for marketplace_name, marketplace_config in config.get("marketplace", {}).items():
            market_type = marketplace_type(marketplace_name, marketplace_config)
            if market_type not in supported_marketplaces:
                raise ValueError(
                    f"Marketplace {hilight(market_type)} is not supported. Supported marketplaces are: {supported_marketplaces.keys()}"
                )
            market_class = supported_marketplaces[market_type]
            unsupported = sorted(set(marketplace_config) - option_names(market_class.config_class))
            if unsupported:
                raise ValueError(
                    f"Marketplace {hilight(marketplace_name)} sets {', '.join(unsupported)}, which "
                    f"{market_type} marketplaces do not have."
                )
            if "search_region" in marketplace_config and not market_class.supports_regions:
                raise ValueError(
                    f"Marketplace {hilight(marketplace_name)} sets search_region, but [region.*] "
                    f"sections are for Facebook; {market_type} marketplaces cannot use them."
                )
            self.marketplace[marketplace_name] = market_class.get_config(
                name=marketplace_name,
                monitor_config=self.monitor,
                **{**marketplace_config, "market_type": market_type},
            )
            lan = self.marketplace[marketplace_name].language
            if lan is None:
                continue
            # no exact match is required
            if lan.split("_")[0] not in {x.split("_")[0] for x in self.translator}:
                raise ValueError(f"Translation for language {lan} is not supported.")

    def get_user_config(self: "Config", config: Dict[str, Any]) -> None:
        # check for required fields in each user
        self.user: Dict[str, UserConfig] = {}
        for user_name, user_config in config.get("user", {}).items():
            self.user[user_name] = User.get_config(name=user_name, **user_config)

    def get_region_config(self: "Config", config: Dict[str, Any]) -> None:
        # check for required fields in each user
        self.region: Dict[str, RegionConfig] = {}
        for region_name, region_config in config.get("region", {}).items():
            self.region[region_name] = RegionConfig(name=region_name, **region_config)

    @staticmethod
    def _check_item_options(
        item_name: str,
        values: Dict[str, Any],
        classes: Dict[str, Type[Marketplace]],
        logger: Logger | None,
    ) -> None:
        """Options no marketplace of the item has are errors; some of them, a warning.

        An option that only some of the item's marketplaces have is used where it exists and
        left out elsewhere.
        """
        if not classes:
            return
        missing = {
            m: set(values) - option_names(market_class.item_config_class)
            for m, market_class in classes.items()
        }
        nowhere = sorted(set.intersection(*missing.values()))
        if nowhere:
            types = sorted({c.market_type for c in classes.values()})
            raise ValueError(
                f"Item {hilight(item_name)} sets {', '.join(nowhere)}, which "
                f"{' and '.join(types)} marketplaces do not have."
            )
        for marketplace_name, keys in missing.items():
            if not keys:
                continue
            message = (
                f"Item {item_name}: {', '.join(sorted(keys))} not used in marketplace "
                f"{marketplace_name} ({classes[marketplace_name].market_type} marketplaces do "
                "not have it)."
            )
            if logger:
                logger.warning(f"""{hilight("[Config]", "fail")} {message}""")
            else:
                warnings.warn(message, stacklevel=2)
        if "search_region" in values:
            for marketplace_name, market_class in classes.items():
                if not market_class.supports_regions:
                    raise ValueError(
                        f"Item {hilight(item_name)} sets search_region, but [region.*] sections "
                        f"are for Facebook; marketplace {marketplace_name} cannot use them."
                    )

    def get_item_config(
        self: "Config", config: Dict[str, Any], logger: Logger | None = None
    ) -> None:
        # check for required fields in each user

        self.item = {}
        self.item_targets = {}
        markets: Dict[str, Any] = config.get("marketplace", {})
        for item_name, item_config in config.get("item", {}).items():
            targets = item_marketplaces(item_name, item_config, markets)
            classes = {m: supported_marketplaces[marketplace_type(m, markets[m])] for m in targets}
            types = [c.market_type for c in classes.values()]
            # a location of its own is fine in sections of different types, each of which takes
            # its value (search_city tables), but not in two of one type: the same place twice
            if len(set(types)) < len(types):
                location = {
                    k
                    for c in classes.values()
                    for k in location_keys(cast(Any, c.item_config_class))
                }
                own = [key for key in item_config if key in location]
                if own:
                    raise ValueError(
                        f"Item {hilight(item_name)} sets {', '.join(own)} but is searched in "
                        f"marketplaces {', '.join(targets)}, which have their own locations. "
                        f"Set marketplace = {targets[0]!r} (or another one) in the item, or "
                        "move the location to the marketplace sections."
                    )
            values = {x: y for x, y in item_config.items() if x != "marketplace"}
            self._check_item_options(item_name, values, classes, logger)
            built: Dict[str, TItemConfig] = {}
            for marketplace_name, market_class in classes.items():
                allowed = option_names(market_class.item_config_class)
                built[marketplace_name] = market_class.get_item_config(
                    name=item_name,
                    marketplace=marketplace_name,
                    **{k: copy.deepcopy(v) for k, v in values.items() if k in allowed},
                )
            if built:
                self.item_targets[item_name] = built
                self.item[item_name] = next(iter(built.values()))

    def validate_sections(
        self: "Config", config: Dict[str, Any], *, partial: bool = False
    ) -> None:
        # check for required sections
        for required_section in [] if partial else ["marketplace", "user", "item"]:
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

    def validate_marketplaces(self: "Config") -> None:
        """Aimm searches only while logged in: logged-out searches fail unpredictably."""
        for marketplace in self.marketplace.values():
            if marketplace.enabled is False:
                continue
            if "username" not in option_names(type(marketplace)):
                continue  # a marketplace searched without logging in
            username = getattr(marketplace, "username", None)
            password = getattr(marketplace, "password", None)
            if not username or not password:
                raise ValueError(
                    f"Marketplace {hilight(marketplace.name)} needs a Facebook username and "
                    "password: aimm searches only while logged in. Set them in "
                    f"[marketplace.{marketplace.name}], e.g. "
                    'username = "${FACEBOOK_USERNAME}" and password = "${FACEBOOK_PASSWORD}", '
                    "or set the FACEBOOK_USERNAME and FACEBOOK_PASSWORD environment variables."
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
        """Set up each user's channels: one for each notification section the user receives."""
        for config in self.user.values():
            self.validate_digest_with(config)
            for notification_name in config.notify_with or []:
                if notification_name not in self.notification:
                    raise ValueError(
                        f"User {hilight(config.name)} specifies an undefined notification method {notification_name}."
                    )
            config._channels = user_channels(config, self.notification)

    def validate_digest_with(self: "Config", config: UserConfig) -> None:
        """The digest goes to some of the notifications that the user receives."""
        if config.digest_with is None:
            return
        received = [
            name
            for name in (
                config.notify_with if config.notify_with is not None else self.notification.keys()
            )
            if name in self.notification and self.notification[name].enabled is not False
        ]
        for name in config.digest_with:
            if name not in received:
                raise ValueError(
                    f"User {hilight(config.name)} digest_with names {name}, which is not an "
                    f"enabled notification the user receives ({', '.join(received) or 'none'})."
                )

    def item_configs(self: "Config") -> List[TItemConfig]:
        """Every item's config for every marketplace it is searched in."""
        return [config for targets in self.item_targets.values() for config in targets.values()]

    def expand_regions(self: "Config") -> None:
        # if region is specified in other section, they must exist
        for config in chain(self.marketplace.values(), self.item_configs()):
            if config.search_region is None:
                continue
            config.city_name = []
            config.search_city = []
            config.radius = []
            config.currency = []

            for region in config.search_region:
                if region not in self.region:
                    raise ValueError(
                        f"Region {hilight(region)} specified in {hilight(config.name)} does not exist."
                    )
                region_config: RegionConfig = self.region[region]
                if region_config.enabled is False:
                    continue
                # avoid duplicated addition of search_city
                for entry, city_name, radius, currency in zip(
                    region_config.search_city or [],
                    region_config.city_name or [],
                    region_config.radius or [],
                    # a region without currency (only the built-in ones set it) has none for
                    # each city: an empty list would make zip() yield no city at all
                    region_config.currency or [cast(Any, None)] * len(region_config.search_city),
                ):
                    # this section's value of the city (a region may list them by type)
                    search_city = location_value(entry, type(config).location_type)
                    if search_city is None:
                        raise ValueError(
                            f"Region {hilight(region)}, used by {hilight(config.name)}, has no "
                            f"{type(config).location_type} value for {entry}."
                        )
                    try:
                        config.check_search_city(search_city)
                    except ValueError as e:
                        raise ValueError(
                            f"Region {hilight(region)}, used by {hilight(config.name)}: {e}"
                        ) from e
                    if search_city not in config.search_city:
                        config.search_city.append(search_city)
                        config.city_name.append(city_name)
                        config.radius.append(radius)
                        config.currency.append(currency)

    def validate_items(self: "Config") -> None:
        # if item is specified in other section, they must exist
        for marketplace_config in self.marketplace.values():
            if marketplace_config.enabled is False:
                continue
            for targets in self.item_targets.values():
                item_config = targets.get(marketplace_config.name)
                if item_config is None or item_config.enabled is False:
                    continue
                if not item_config.search_city and not marketplace_config.search_city:
                    raise ValueError(
                        f"No search_city or search_region is specified for {item_config.name} or market {marketplace_config.name}"
                    )
