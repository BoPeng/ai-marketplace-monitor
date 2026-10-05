"""expand() and normalize(): the two behavior-equivalent forms of a user config."""

import copy
from typing import Any, Dict, Tuple

from ..config import Config
from .compact import compact
from .effective import check_equivalent
from .model import (
    NormalizeError,
    NormalizeResult,
    describe_changes,
    order_config,
    plain,
)
from .notifications import normalize_notifications
from .pushdown import Notes, push_down


def _expand(
    user_cfg: Dict[str, Any], system_cfg: Dict[str, Any], partial: bool
) -> Tuple[Dict[str, Any], Notes]:
    cfg = copy.deepcopy(user_cfg)
    try:
        loaded = Config.from_dicts(system_cfg, cfg, partial=partial)
    except Exception as e:
        raise NormalizeError(f"Config is not valid: {plain(e)}") from e
    normalize_notifications(cfg, loaded)
    notes = push_down(cfg)
    result = order_config(cfg)
    check_equivalent(system_cfg, user_cfg, result, partial=partial)
    return result, notes


def expand(
    user_cfg: Dict[str, Any], system_cfg: Dict[str, Any], *, partial: bool = False
) -> NormalizeResult:
    """Return the expanded form of a valid user config (memory only); never mutates the input.

    ``partial`` accepts a config without every section the monitor needs (see
    ``Config.from_dicts``).
    """
    result, notes = _expand(user_cfg, system_cfg, partial)
    return NormalizeResult(result, describe_changes(user_cfg, result, notes))


def normalize(
    user_cfg: Dict[str, Any], system_cfg: Dict[str, Any], *, partial: bool = False
) -> NormalizeResult:
    """compact(expand(x)): the only form ever written to disk; never mutates the input."""
    expanded, expand_notes = _expand(user_cfg, system_cfg, partial)
    compacted, compact_notes = compact(expanded)
    result = order_config(compacted)
    check_equivalent(system_cfg, user_cfg, result, partial=partial)
    return NormalizeResult(
        result, describe_changes(user_cfg, result, {**expand_notes, **compact_notes})
    )
