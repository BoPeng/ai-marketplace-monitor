"""What a config actually does, and a check that two configs do the same thing."""

import json
from dataclasses import asdict
from typing import Any, Dict, List, Tuple

from ..config import Config
from ..marketplace import resolve_option
from ..user import UserConfig
from .model import AI_PROMPT_ITEM_ONLY, COMMON_OPTIONS, NormalizeError, mask

_USER_EXCLUDE = {"name", "request", "notify_with"}
_MARKETPLACE_EXCLUDE = {*COMMON_OPTIONS, "name", "request", "monitor_config"}
_ITEM_ONLY_FIELDS = ("search_phrases", "keywords", "antikeywords", "description")
_MISSING = "<missing>"


def _user_view(user: UserConfig) -> Dict[str, Any]:
    return {
        k: v
        for k, v in asdict(user).items()
        if k not in _USER_EXCLUDE and not k.startswith("_")
    }


def _item_view(config: Config, name: str) -> Dict[str, Any]:
    item = config.item[name]
    # Config.get_item_config always binds an item to one marketplace
    assert item.marketplace is not None
    market = config.marketplace[item.marketplace]
    entry: Dict[str, Any] = {"marketplace": item.marketplace, "enabled": item.enabled}
    entry.update({k: getattr(item, k) for k in _ITEM_ONLY_FIELDS})
    for key in COMMON_OPTIONS:
        if key not in ("search_region", "notify", "ai"):
            entry[key] = resolve_option(key, item, market)
    for key in AI_PROMPT_ITEM_ONLY:
        entry[f"ai_prompt:{key}"] = resolve_option(key, item, market, site="ai_prompt")
    users = resolve_option("notify", item, market) or list(config.user)
    entry["notify"] = {u: _user_view(config.user[u]) for u in users}
    ai = resolve_option("ai", item, market)
    entry["ai"] = list(config.ai) if ai is None else list(ai)
    return entry


def effective_view(config: Config) -> Dict[str, Any]:
    """JSON-able description of everything the config makes the monitor do."""
    view = {
        "marketplace": {
            n: {k: v for k, v in asdict(m).items() if k not in _MARKETPLACE_EXCLUDE}
            for n, m in config.marketplace.items()
        },
        "ai": {
            n: {k: v for k, v in asdict(a).items() if k != "request"}
            for n, a in config.ai.items()
        },
        "monitor": {k: v for k, v in asdict(config.monitor).items() if k != "request"},
        "translation": {
            n: {"locale": t.locale, "dictionary": t.dictionary}
            for n, t in config.translator.items()
        },
        "item": {name: _item_view(config, name) for name in config.item},
    }
    return json.loads(json.dumps(view, default=str))


KeyPath = Tuple[str, ...]


def _diff(a: Any, b: Any, path: KeyPath = ()) -> List[Tuple[KeyPath, Any, Any]]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: List[Tuple[KeyPath, Any, Any]] = []
        for key in [*a, *(k for k in b if k not in a)]:
            out.extend(_diff(a.get(key, _MISSING), b.get(key, _MISSING), (*path, key)))
        return out
    return [] if a == b else [(path, a, b)]


def _is_allowed(path: KeyPath, after_view: Dict[str, Any]) -> bool:
    if len(path) != 3 or path[0] != "item" or not path[2].startswith("ai_prompt:"):
        return False
    key = path[2].split(":", 1)[1]
    entry = after_view["item"][path[1]]
    return key in AI_PROMPT_ITEM_ONLY and entry[path[2]] == entry[key]


def _mask_deep(value: Any) -> Any:
    """Mask sensitive values at every depth of nested dicts and lists."""
    if isinstance(value, dict):
        return {k: mask(k, _mask_deep(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_deep(v) for v in value]
    return value


def _format(path: KeyPath, old: Any, new: Any) -> str:
    key = next((p for p in reversed(path) if mask(p, "x") != "x"), path[-1])
    return f"{'.'.join(path)}: {mask(key, _mask_deep(old))!r} -> {mask(key, _mask_deep(new))!r}"


def check_equivalent(
    system_cfg: Dict[str, Any], before: Dict[str, Any], after: Dict[str, Any]
) -> List[str]:
    """Raise NormalizeError unless `after` behaves like `before`; return allowed diffs."""
    try:
        before_view = effective_view(Config.from_dicts(system_cfg, before))
    except Exception as e:
        raise NormalizeError(f"Config is not valid: {e}") from e
    try:
        after_view = effective_view(Config.from_dicts(system_cfg, after))
    except Exception as e:
        raise NormalizeError(f"Normalized config does not load: {e}") from e
    allowed: List[str] = []
    errors: List[str] = []
    for path, old, new in _diff(before_view, after_view):
        if _is_allowed(path, after_view):
            allowed.append(".".join(path))
        else:
            errors.append(_format(path, old, new))
    if errors:
        raise NormalizeError("Normalization would change behavior:\n" + "\n".join(errors))
    return allowed
