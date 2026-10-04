"""expand() and normalize(): the two behavior-equivalent forms of a user config."""

import copy
from typing import Any, Dict

from ..config import Config
from .effective import check_equivalent
from .model import NormalizeError, NormalizeResult, describe_changes, order_config
from .notifications import normalize_notifications
from .pushdown import push_down


def expand(user_cfg: Dict[str, Any], system_cfg: Dict[str, Any]) -> NormalizeResult:
    """Return the expanded form of a valid user config (memory only); never mutates the input."""
    cfg = copy.deepcopy(user_cfg)
    try:
        loaded = Config.from_dicts(system_cfg, cfg)
    except Exception as e:
        raise NormalizeError(f"Config is not valid: {e}") from e
    normalize_notifications(cfg, loaded)
    notes = push_down(cfg)
    result = order_config(cfg)
    check_equivalent(system_cfg, user_cfg, result)
    return NormalizeResult(result, describe_changes(user_cfg, result, notes))
