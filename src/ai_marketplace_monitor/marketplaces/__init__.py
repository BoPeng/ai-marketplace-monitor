"""The marketplaces aimm searches: the shared base class and one package per marketplace.

``supported_marketplaces`` maps a ``market_type`` to its class. A ``[marketplace.<name>]``
section's type is resolved by ``marketplace_type``.
"""

from typing import Any, Dict, Mapping, Type

from ..utils import hilight
from .base import Marketplace
from .facebook import FacebookMarketplace

__all__ = ["marketplace_class", "marketplace_type", "supported_marketplaces"]

supported_marketplaces: Dict[str, Type[Marketplace]] = {"facebook": FacebookMarketplace}


def marketplace_type(name: str, section: Mapping[str, Any]) -> str:
    """The type of a ``[marketplace.<name>]`` section, as given in the config file.

    Its ``market_type`` if it sets one; otherwise its name, if that names a supported
    marketplace (``[marketplace.facebook]``); otherwise ``facebook``. Section names are free:
    ``[marketplace.mymarket]`` is a Facebook marketplace unless it says otherwise.
    """
    market_type = section.get("market_type")
    if market_type is None or market_type == "":
        return name if name in supported_marketplaces else "facebook"
    if not isinstance(market_type, str):
        raise ValueError(f"Marketplace {hilight(name)} market_type must be a string.")
    return market_type.lower()


def marketplace_class(marketplace_config: Any) -> Type[Marketplace]:
    """The class of a parsed marketplace section (its resolved ``market_type``)."""
    return supported_marketplaces[marketplace_config.market_type or "facebook"]
