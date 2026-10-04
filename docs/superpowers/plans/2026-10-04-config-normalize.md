# Config Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `request` field to every config section (making `[translation.*]` a `BaseConfig` too) and an internal `ai_marketplace_monitor.normalize` package: `expand()` produces the explicit form an AI reads and edits (memory only), and `normalize()` = compact(expand(x)) produces the only form ever written to disk, both with provably identical runtime behavior.

**Architecture:** Pure functions over the parsed-but-unprocessed TOML dict. A shared `resolve_option` helper becomes the single definition of how item options fall back to marketplace options; runtime call sites and the normalizer both use it. Every `expand`/`normalize` call loads input and output through the real `Config` loader (new `Config.from_dicts`) and compares an `effective_view` of each, raising `NormalizeError` on any behavior difference except the one documented AI-prompt-price fix.

**Tech Stack:** Python 3.10+ dataclasses, `tomllib`/`tomli`, pytest (`uv run pytest`), ruff, mypy (`uv run mypy src`).

**Spec:** `docs/superpowers/specs/2026-10-04-config-normalize-design.md` (issue BoPeng/ai-marketplace-monitor#362). Read it before starting any task.

## Global Constraints

- **Prerequisite:** BoPeng/ai-marketplace-monitor#364 (Spanish translation fix + `TranslationConfig`) must be merged into `main`, and `main` merged into `config-normalize`, before Task 1.
- Branch: `config-normalize`. Commit after every task; end each commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No file writes, no network, no `webui` imports inside `src/ai_marketplace_monitor/normalize/`.
- `expand`/`normalize`/`compact` never mutate their input dicts; raw values are copied verbatim (`"1h"` stays `"1h"`, `${VAR}` stays a placeholder).
- Section type order: `monitor`, `ai`, `marketplace`, `user`, `notification`, `region`, `item`, `translation`. Within a type: input order, never sorted. Within a section: `request`, `enabled`, then dataclass field order, then unknown keys in input order (for `[translation.*]`: `request`, `enabled`, `locale`, then the words in input order).
- The only allowed effective-behavior difference: `item.<name>.ai_prompt:min_price` / `ai_prompt:max_price` may change, and only to the value the search uses.
- Code style: every function fully annotated (ruff `ANN`), methods annotate `self: "ClassName"`, package `__init__.py` needs a docstring (ruff `D104`), line length 99. Run `uv run ruff check src tests` and `uv run mypy src` before each commit.
- Test runner: `uv run pytest`. Full suite must stay green after every task.

## File Structure

| File | Responsibility |
|---|---|
| `src/ai_marketplace_monitor/utils.py` (modify) | `BaseConfig.request`, `handle_request`, hash exclusion; `TRANSLATION_FIELDS` gains `request` (`TranslationConfig` itself comes from #364); `is_sensitive_key` (moved from webui) |
| `src/ai_marketplace_monitor/webui/secrets_redact.py` (modify) | import `is_sensitive_key` instead of defining it |
| `src/ai_marketplace_monitor/config.py` (modify) | `SYSTEM_CONFIG`, `load_config_dicts`, `Config.from_dicts`, `Config._load`; skip `request` in notification merge |
| `src/ai_marketplace_monitor/marketplace.py` (modify) | `Fallback`, `COMMON_OPTION_FALLBACK`, `SITE_FALLBACK`, `resolve_option` |
| `src/ai_marketplace_monitor/facebook.py`, `monitor.py`, `ai.py` (modify) | call `resolve_option` instead of inline fallbacks |
| `src/ai_marketplace_monitor/normalize/__init__.py` | public exports |
| `src/ai_marketplace_monitor/normalize/model.py` | `Change`, `NormalizeResult`, `NormalizeError`, constants, ordering, `describe_changes` |
| `src/ai_marketplace_monitor/normalize/effective.py` | `effective_view`, `check_equivalent` |
| `src/ai_marketplace_monitor/normalize/notifications.py` | canonical users + `[notification.*]` |
| `src/ai_marketplace_monitor/normalize/pushdown.py` | marketplace → item push-down, `bound_marketplace` |
| `src/ai_marketplace_monitor/normalize/core.py` | `expand()` and `normalize()` |
| `src/ai_marketplace_monitor/normalize/compact.py` | `compact()`, the internal second step of `normalize()` |
| `docs/README.md`, `docs/example_config.toml`, `CHANGELOG.md` (modify) | docs, fix invalid example, changelog |
| `tests/normalize_util.py` | shared test helpers (`parse`, `system_cfg`, `dumps`) |
| `tests/test_config_request.py`, `tests/test_config_loading.py`, `tests/test_option_fallback.py`, `tests/test_resolve_option.py`, `tests/test_normalize_model.py`, `tests/test_normalize_effective.py`, `tests/test_normalize_notifications.py`, `tests/test_normalize_pushdown.py`, `tests/test_normalize_compact.py`, `tests/test_normalize_properties.py` | tests |

---

### Task 1: `request` field on `BaseConfig`

**Files:**
- Modify: `src/ai_marketplace_monitor/utils.py:282-329` (`BaseConfig`)
- Modify: `src/ai_marketplace_monitor/config.py:261` (`expand_notifications` excluded keys)
- Modify: `src/ai_marketplace_monitor/utils.py` (`TRANSLATION_FIELDS`, from #364)
- Modify: `docs/README.md` ("Additional options" table near line 370)
- Test: `tests/test_config_request.py`

**Interfaces:**
- Produces: `BaseConfig.request: str | None` (third field, after `name`, `enabled`); `BaseConfig.hash` ignores `request`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_request.py
from pathlib import Path

import pytest

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.facebook import FacebookItemConfig

BASE = """
[marketplace.facebook]
search_city = "houston"
request = "I live in Houston"

[user.alice]
pushbullet_token = "abc"
request = "Alice gets pushbullet"

[item.bike]
search_phrases = "bike"
request = "a road bike"

[ai.openai]
api_key = "sk-test"
request = "use openai"

[notification.tg]
telegram_token = "123:abc"
telegram_chat_id = "1"
request = "telegram bot"

[region.home]
search_city = ["houston"]
request = "home region"

[monitor]
request = "defaults"
"""


def _load(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return Config([path])


def test_request_accepted_on_every_base_config_section(tmp_path: Path) -> None:
    cfg = _load(tmp_path, BASE)
    assert cfg.marketplace["facebook"].request == "I live in Houston"
    assert cfg.item["bike"].request == "a road bike"
    assert cfg.ai["openai"].request == "use openai"
    assert cfg.notification["tg"].request == "telegram bot"
    assert cfg.region["home"].request == "home region"
    assert cfg.monitor.request == "defaults"


def test_notification_request_is_not_merged_into_user(tmp_path: Path) -> None:
    # alice has no notify_with, so notification.tg is merged into her at load time
    cfg = _load(tmp_path, BASE)
    assert cfg.user["alice"].telegram_token == "123:abc"
    assert cfg.user["alice"].request == "Alice gets pushbullet"


def test_request_must_be_a_string() -> None:
    with pytest.raises(ValueError, match="request must be a string"):
        FacebookItemConfig(name="bike", search_phrases=["bike"], request=3)  # type: ignore[arg-type]


def test_request_is_not_env_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIMM_TEST_REQUEST", "expanded")
    item = FacebookItemConfig(name="bike", search_phrases=["bike"], request="${AIMM_TEST_REQUEST}")
    assert item.request == "${AIMM_TEST_REQUEST}"


def test_translation_request_is_not_a_word(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        BASE + '[translation.de]\nrequest = "Germany"\nlocale = "German"\nCondition = "Zustand"\n',
    )
    assert cfg.translator["de"].dictionary == {"Condition": "Zustand"}


def test_request_does_not_change_hash() -> None:
    plain = FacebookItemConfig(name="bike", search_phrases=["bike"])
    with_request = FacebookItemConfig(name="bike", search_phrases=["bike"], request="anything")
    assert plain.hash == with_request.hash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_request.py -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'request'`.

- [ ] **Step 3: Implement**

In `utils.py`, change `BaseConfig` to:

```python
@dataclass
class BaseConfig:
    name: str
    enabled: bool | None = None
    # free-text intent for this section; never used at runtime, never env-expanded
    request: str | None = None

    def __post_init__(self: "BaseConfig") -> None:
        """Handle all methods that start with 'handle_' in the dataclass."""
        for f in fields(self):
            # test the type of field f, if it is a string or a list of string
            # try to expand the string with environment variables
            fvalue = getattr(self, f.name)
            if f.name != "request":
                if isinstance(fvalue, str):
                    setattr(self, f.name, self._value_from_environ(fvalue))
                elif isinstance(fvalue, list) and all(isinstance(x, str) for x in fvalue):
                    setattr(self, f.name, [self._value_from_environ(x) for x in fvalue])

            handle_method = getattr(self, f"handle_{f.name}", None)
            if handle_method:
                handle_method()
```

Add after `handle_enabled`:

```python
    def handle_request(self: "BaseConfig") -> None:
        if self.request is None:
            return
        if not isinstance(self.request, str):
            raise ValueError(f"Section {hilight(self.name)} request must be a string.")
```

Replace the `hash` property:

```python
    @property
    def hash(self: "BaseConfig") -> str:
        # editing `request` must not invalidate cached AI results
        values = asdict(self)
        values.pop("request", None)
        return hash_dict(values)
```

In `utils.py`, make `request` a translation setting rather than a word (`TRANSLATION_FIELDS` comes from #364):

```python
TRANSLATION_FIELDS: Tuple[str, ...] = ("request", "enabled", "locale")
```

In `config.py` `expand_notifications`, change `if key not in ("type", "name") and value is not None:` to:

```python
                    if key not in ("type", "name", "request") and value is not None:
```

In `docs/README.md`, add a row under the `enabled` row of the "Additional options" table:

```markdown
| `request` | Optional          | String    | Your own description of what you want from this section. Not used when searching; reserved for AI-assisted configuration. Accepted by all sections. |
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config_request.py -v && uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_marketplace_monitor/utils.py src/ai_marketplace_monitor/config.py docs/README.md tests/test_config_request.py
git commit -m "feat: add request field to every config section (#362)"
```

---

### Task 2: Translation sections become `BaseConfig` — done in #364

Implemented and tested in BoPeng/ai-marketplace-monitor#364 (see **Prerequisite** under Global Constraints). Nothing to do here beyond verifying it is present.

**Interfaces (provided by #364, used by later tasks):**
- `ai_marketplace_monitor.utils.TRANSLATION_FIELDS: Tuple[str, ...]` — `("enabled", "locale")` in #364; Task 1 makes it `("request", "enabled", "locale")`
- `@dataclass TranslationConfig(BaseConfig)` with `locale: str | None = None`, `dictionary: Dict[str, str]`
- `Translator.dictionary -> Dict[str, str]` (read-only copy)
- `Config.translator: Dict[str, Translator]` holds **enabled** translations only

- [ ] **Step 1: Verify**

Run: `uv run pytest tests/test_translations.py -v`
Expected: PASS (includes `test_translation_section_is_a_base_config`).

---

### Task 3: `load_config_dicts` and `Config.from_dicts`

**Files:**
- Modify: `src/ai_marketplace_monitor/config.py:1-97`
- Modify: `docs/example_config.toml` (`search_city = 'another city'` → `'anothercity'`)
- Test: `tests/test_config_loading.py`, create `tests/normalize_util.py`

**Interfaces:**
- Produces: `config.SYSTEM_CONFIG: Path`; `load_config_dicts(config_files: List[Path], logger: Logger | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]` returning `(system, merged_user)`; `Config.from_dicts(system: Dict[str, Any], user: Dict[str, Any], logger: Logger | None = None) -> Config` (does not mutate its arguments).
- Produces (tests): `tests/normalize_util.py` with `parse(text: str) -> Dict[str, Any]`, `system_cfg() -> Dict[str, Any]`, `dumps(cfg: Dict[str, Any]) -> str`, `EXAMPLES: List[Path]`.

- [ ] **Step 1: Write the helper and failing tests**

```python
# tests/normalize_util.py
"""Helpers shared by config loading and normalization tests."""

import json
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.config import SYSTEM_CONFIG

ROOT = Path(__file__).parent.parent
EXAMPLES: List[Path] = [ROOT / "docs" / "minimal_config.toml", ROOT / "docs" / "example_config.toml"]


def parse(text: str) -> Dict[str, Any]:
    return tomllib.loads(textwrap.dedent(text))


def system_cfg() -> Dict[str, Any]:
    with open(SYSTEM_CONFIG, "rb") as f:
        return tomllib.load(f)


def dumps(cfg: Dict[str, Any]) -> str:
    """Order-sensitive serialization (plain dict == ignores key order)."""
    return json.dumps(cfg, default=str)
```

```python
# tests/test_config_loading.py
import copy
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict

import pytest

from ai_marketplace_monitor.config import Config, load_config_dicts
from tests.normalize_util import EXAMPLES


def _snapshot(cfg: Config) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in vars(cfg).items():
        if is_dataclass(value):
            out[key] = asdict(value)
        else:
            out[key] = {
                name: asdict(v) if is_dataclass(v) else vars(v) for name, v in value.items()
            }
    return out


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_from_dicts_matches_file_loading(path: Path) -> None:
    system, user = load_config_dicts([path])
    assert _snapshot(Config.from_dicts(system, user)) == _snapshot(Config([path]))


def test_from_dicts_does_not_mutate_inputs() -> None:
    system, user = load_config_dicts(EXAMPLES[:1])
    system_before, user_before = copy.deepcopy(system), copy.deepcopy(user)
    Config.from_dicts(system, user)
    assert system == system_before
    assert user == user_before


def test_load_config_dicts_merges_user_files(tmp_path: Path) -> None:
    first = tmp_path / "a.toml"
    first.write_text('[marketplace.facebook]\nsearch_city = "houston"\n[user.u]\npushbullet_token = "x"\n')
    second = tmp_path / "b.toml"
    second.write_text('[item.bike]\nsearch_phrases = "bike"\n')
    system, user = load_config_dicts([first, second])
    assert "region" in system
    assert set(user) == {"marketplace", "user", "item"}
    assert "bike" in Config.from_dicts(system, user).item


def test_parse_error_message_kept(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("[item\n")
    with pytest.raises(ValueError, match="Error parsing config file"):
        load_config_dicts([bad])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_loading.py -v`
Expected: FAIL — `ImportError: cannot import name 'SYSTEM_CONFIG'`.

- [ ] **Step 3: Implement**

In `config.py` add `import copy` and `Tuple` to the `typing` import, then replace everything from `def __init__` through the end of the call sequence (current lines 61-97) with:

```python
SYSTEM_CONFIG = Path(__file__).parent / "config.toml"


def _load_toml(path: Path, logger: Logger | None = None) -> Dict[str, Any]:
    if logger:
        logger.debug(f"""{hilight("[Monitor]", "succ")} config file {hilight(str(path))}""")
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Error parsing config file {path}: {e}") from e


def load_config_dicts(
    config_files: List[Path], logger: Logger | None = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (bundled system config, merged user config) as parsed, unprocessed dicts."""
    system = _load_toml(SYSTEM_CONFIG, logger)
    user = merge_dicts([_load_toml(f, logger) for f in config_files])
    return system, user
```

(Place `SYSTEM_CONFIG`, `_load_toml`, `load_config_dicts` above `class ConfigItem`.) Inside `Config`:

```python
    def __init__(self: "Config", config_files: List[Path], logger: Logger | None = None) -> None:
        system, user = load_config_dicts(config_files, logger)
        self._load(system, user, logger)

    @classmethod
    def from_dicts(
        cls: type["Config"],
        system: Dict[str, Any],
        user: Dict[str, Any],
        logger: Logger | None = None,
    ) -> "Config":
        """Build a Config from already-parsed dicts without mutating them."""
        obj = cls.__new__(cls)
        obj._load(system, user, logger)
        return obj

    def _load(
        self: "Config", system: Dict[str, Any], user: Dict[str, Any], logger: Logger | None
    ) -> None:
        # merge_dicts mutates nested dicts in place, so work on copies
        config = merge_dicts([copy.deepcopy(system), copy.deepcopy(user)])

        self.validate_sections(config)
        self.get_translator_config(config)
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
        self.validate_items()
```

In `docs/example_config.toml`, under `[item.name2]`, change `search_city = 'another city'` to `search_city = 'anothercity'` (the loader rejects spaces; the example never loaded).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config_loading.py -v && uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_marketplace_monitor/config.py docs/example_config.toml tests/normalize_util.py tests/test_config_loading.py
git commit -m "refactor: add load_config_dicts and Config.from_dicts (#362)"
```

---

### Task 4: Characterization tests for item → marketplace option fallback

These pin **current** behavior through real code paths; they must pass on unmodified code. They guard the refactor in Task 5.

**Files:**
- Test: `tests/test_option_fallback.py`

**Interfaces:**
- Consumes: `listing` fixture from root `conftest.py` (location `"houston, tx"`, seller `"some guy"`).

- [ ] **Step 1: Write the tests**

```python
# tests/test_option_fallback.py
"""Pin how item options fall back to marketplace options at each runtime use site."""

from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

from ai_marketplace_monitor.ai import AIResponse, OllamaBackend, OllamaConfig
from ai_marketplace_monitor.facebook import (
    FacebookItemConfig,
    FacebookMarketplace,
    FacebookMarketplaceConfig,
)
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.monitor import MarketplaceMonitor


def _market(**kwargs: Any) -> FacebookMarketplaceConfig:
    kwargs.setdefault("search_city", ["houston"])
    return FacebookMarketplaceConfig(name="facebook", **kwargs)


def _item(**kwargs: Any) -> FacebookItemConfig:
    return FacebookItemConfig(name="bike", search_phrases=["bike"], **kwargs)


def _search_urls(item: FacebookItemConfig, market: FacebookMarketplaceConfig) -> List[str]:
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(market)
    mp.page = MagicMock()
    urls: List[str] = []
    # ruff targets py39, so no parenthesized context managers
    with patch.object(mp, "goto_url", side_effect=urls.append), patch(
        "ai_marketplace_monitor.facebook.FacebookSearchResultPage"
    ) as page_cls, patch("ai_marketplace_monitor.facebook.time.sleep"), patch(
        "ai_marketplace_monitor.facebook.counter"
    ):
        page_cls.return_value.get_listings.return_value = []
        list(mp.search(item))
    return urls


@pytest.mark.parametrize(
    ("key", "item_value", "market_value", "fragment"),
    [
        ("condition", None, ["new"], "itemCondition=new"),
        ("condition", ["used_good"], ["new"], "itemCondition=used_good"),
        ("date_listed", None, [7], "daysSinceListed=7"),
        ("date_listed", [1], [7], "daysSinceListed=1"),
        ("delivery_method", None, ["shipping"], "deliveryMethod=shipping"),
        ("availability", None, ["out"], "availability=out"),
        ("sort_by", None, "new", "sortBy=creation_time_descend"),
        ("max_price", None, "300", "maxPrice=300"),
        ("max_price", "200", "300", "maxPrice=200"),
        ("min_price", None, "100", "minPrice=100"),
        ("category", None, "electronics", "category=electronics"),
    ],
)
def test_search_url_option_fallback(
    key: str, item_value: Any, market_value: Any, fragment: str
) -> None:
    item = _item(**({key: item_value} if item_value is not None else {}))
    url = _search_urls(item, _market(**{key: market_value}))[0]
    assert fragment in url


def test_search_city_empty_item_list_falls_back_to_marketplace() -> None:
    url = _search_urls(_item(search_city=[]), _market(search_city=["houston"]))[0]
    assert url.startswith("https://www.facebook.com/marketplace/houston/search?")


def test_search_city_item_overrides_marketplace() -> None:
    url = _search_urls(_item(search_city=["dallas"]), _market(search_city=["houston"]))[0]
    assert url.startswith("https://www.facebook.com/marketplace/dallas/search?")


def test_radius_from_marketplace_when_item_unset() -> None:
    url = _search_urls(_item(), _market(search_city=["houston"], radius=[50]))[0]
    assert "radius=50" in url


def _check(item: FacebookItemConfig, market: FacebookMarketplaceConfig, listing: Listing) -> bool:
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(market)
    return mp.check_listing(listing, item, description_available=False)


def test_seller_locations_empty_item_list_wins(listing: Listing) -> None:
    assert _check(_item(seller_locations=[]), _market(seller_locations=["dallas"]), listing)


def test_seller_locations_unset_item_uses_marketplace(listing: Listing) -> None:
    assert not _check(_item(), _market(seller_locations=["dallas"]), listing)


def test_exclude_sellers_empty_item_list_wins(listing: Listing) -> None:
    assert _check(_item(exclude_sellers=[]), _market(exclude_sellers=["some guy"]), listing)


def test_exclude_sellers_unset_item_uses_marketplace(listing: Listing) -> None:
    assert not _check(_item(), _market(exclude_sellers=["some guy"]), listing)


def _prompt(
    item: FacebookItemConfig, market: FacebookMarketplaceConfig, listing: Listing
) -> str:
    config = OllamaConfig(name="ollama", base_url="http://localhost:11434", model="m")
    return OllamaBackend(config, logger=None).get_prompt(listing, item, market)


def test_prompt_empty_item_string_wins(listing: Listing) -> None:
    assert "MARKET PROMPT" not in _prompt(_item(prompt=""), _market(prompt="MARKET PROMPT"), listing)


def test_prompt_unset_item_uses_marketplace(listing: Listing) -> None:
    assert "MARKET PROMPT" in _prompt(_item(), _market(prompt="MARKET PROMPT"), listing)


def test_extra_prompt_unset_item_uses_marketplace(listing: Listing) -> None:
    assert "MARKET EXTRA" in _prompt(_item(), _market(extra_prompt="MARKET EXTRA"), listing)


def test_rating_prompt_unset_item_uses_marketplace(listing: Listing) -> None:
    assert "MARKET RATING" in _prompt(_item(), _market(rating_prompt="MARKET RATING"), listing)


def test_ai_prompt_price_ignores_marketplace(listing: Listing) -> None:
    assert "Max price" not in _prompt(_item(), _market(max_price="300"), listing)


def test_ai_prompt_price_uses_item(listing: Listing) -> None:
    assert "Max price 200" in _prompt(_item(max_price="200"), _market(max_price="300"), listing)


def _monitor(*agent_names: str) -> MarketplaceMonitor:
    monitor = MarketplaceMonitor.__new__(MarketplaceMonitor)
    monitor.logger = None
    agents = []
    for name in agent_names:
        agent = MagicMock()
        agent.config.name = name
        agent.evaluate.return_value = name
        agents.append(agent)
    monitor.ai_agents = agents
    return monitor


def test_ai_empty_item_list_disables_ai(listing: Listing) -> None:
    monitor = _monitor("openai")
    result = monitor.evaluate_by_ai(listing, _item(ai=[]), _market(ai=["openai"]))
    assert isinstance(result, AIResponse)
    monitor.ai_agents[0].evaluate.assert_not_called()


def test_ai_unset_item_uses_marketplace(listing: Listing) -> None:
    monitor = _monitor("openai", "claude")
    assert monitor.evaluate_by_ai(listing, _item(), _market(ai=["claude"])) == "claude"


def test_ai_unset_everywhere_uses_all_agents(listing: Listing) -> None:
    monitor = _monitor("openai", "claude")
    assert monitor.evaluate_by_ai(listing, _item(), _market()) == "openai"
```

The remaining `monitor.py` sites (`notify`, `rating`, `start_at`, `search_interval`, `max_search_interval`) live inside long scheduling/search loops that cannot be driven without a browser; they are covered by the rule table in Task 5 plus a line-by-line review that each replacement is the same expression.

- [ ] **Step 2: Run tests (must pass on current code)**

Run: `uv run pytest tests/test_option_fallback.py -v`
Expected: all PASS. If any fails, the test is wrong about current behavior — fix the test, never the source, in this task.

- [ ] **Step 3: Commit**

```bash
git add tests/test_option_fallback.py
git commit -m "test: characterize item/marketplace option fallback (#362)"
```

---

### Task 5: `resolve_option` and call-site refactor

**Files:**
- Modify: `src/ai_marketplace_monitor/marketplace.py` (add after the imports / before `MarketItemCommonConfig`)
- Modify: `src/ai_marketplace_monitor/facebook.py:18` (import), `:389-496` (`search`), `:652-671` (`check_listing`)
- Modify: `src/ai_marketplace_monitor/monitor.py:18` (import), `:171-173`, `:232-241`, `:362`, `:389-399`, `:729-733`, `:771-776`
- Modify: `src/ai_marketplace_monitor/ai.py:13` (import), `:194-195`, `:212-231`
- Test: `tests/test_resolve_option.py`

**Interfaces:**
- Produces (in `ai_marketplace_monitor.marketplace`):
  - `class Fallback(Enum)`: `TRUTHY`, `NOT_NONE`, `ITEM_ONLY`
  - `COMMON_OPTION_FALLBACK: Dict[str, Fallback]` — every common option except `search_region`
  - `SITE_FALLBACK: Dict[Tuple[str, str], Fallback]` — `{("ai_prompt", "min_price"): ITEM_ONLY, ("ai_prompt", "max_price"): ITEM_ONLY}`
  - `resolve_option(key: str, item: Any, marketplace: Any, site: str = "search") -> Any`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_resolve_option.py
from dataclasses import fields
from types import SimpleNamespace

import pytest

from ai_marketplace_monitor.facebook import FacebookMarketItemCommonConfig
from ai_marketplace_monitor.marketplace import (
    COMMON_OPTION_FALLBACK,
    Fallback,
    MarketItemCommonConfig,
    resolve_option,
)
from ai_marketplace_monitor.utils import BaseConfig


def test_table_covers_every_common_option_except_search_region() -> None:
    base = {f.name for f in fields(BaseConfig)}
    common = {
        f.name
        for cls in (MarketItemCommonConfig, FacebookMarketItemCommonConfig)
        for f in fields(cls)
    } - base
    assert set(COMMON_OPTION_FALLBACK) == common - {"search_region"}


@pytest.mark.parametrize(
    "key", [k for k, rule in COMMON_OPTION_FALLBACK.items() if rule is Fallback.TRUTHY]
)
def test_truthy_rule(key: str) -> None:
    market = SimpleNamespace(**{key: ["m"]})
    assert resolve_option(key, SimpleNamespace(**{key: None}), market) == ["m"]
    assert resolve_option(key, SimpleNamespace(**{key: []}), market) == ["m"]
    assert resolve_option(key, SimpleNamespace(**{key: ["i"]}), market) == ["i"]


@pytest.mark.parametrize(
    "key", [k for k, rule in COMMON_OPTION_FALLBACK.items() if rule is Fallback.NOT_NONE]
)
def test_not_none_rule(key: str) -> None:
    market = SimpleNamespace(**{key: ["m"]})
    assert resolve_option(key, SimpleNamespace(**{key: None}), market) == ["m"]
    assert resolve_option(key, SimpleNamespace(**{key: []}), market) == []


def test_expected_not_none_keys() -> None:
    not_none = {k for k, rule in COMMON_OPTION_FALLBACK.items() if rule is Fallback.NOT_NONE}
    assert not_none == {
        "ai",
        "exclude_sellers",
        "seller_locations",
        "prompt",
        "extra_prompt",
        "rating_prompt",
    }


def test_ai_prompt_site_prices_are_item_only() -> None:
    item, market = SimpleNamespace(min_price=None), SimpleNamespace(min_price="100")
    assert resolve_option("min_price", item, market, site="ai_prompt") is None
    assert resolve_option("min_price", item, market) == "100"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_resolve_option.py -v`
Expected: FAIL — `ImportError: cannot import name 'COMMON_OPTION_FALLBACK'`.

- [ ] **Step 3: Implement `resolve_option`**

In `marketplace.py` (add `Tuple` to the `typing` import), insert before `@dataclass class MarketItemCommonConfig`:

```python
class Fallback(Enum):
    """How an item option falls back to the marketplace option."""

    TRUTHY = "truthy"  # item.x or marketplace.x
    NOT_NONE = "not_none"  # item.x if item.x is not None else marketplace.x
    ITEM_ONLY = "item_only"  # marketplace value ignored


COMMON_OPTION_FALLBACK: Dict[str, Fallback] = {
    "ai": Fallback.NOT_NONE,
    "exclude_sellers": Fallback.NOT_NONE,
    "seller_locations": Fallback.NOT_NONE,
    "prompt": Fallback.NOT_NONE,
    "extra_prompt": Fallback.NOT_NONE,
    "rating_prompt": Fallback.NOT_NONE,
    "notify": Fallback.TRUTHY,
    "search_city": Fallback.TRUTHY,
    "city_name": Fallback.TRUTHY,
    "radius": Fallback.TRUTHY,
    "currency": Fallback.TRUTHY,
    "search_interval": Fallback.TRUTHY,
    "max_search_interval": Fallback.TRUTHY,
    "start_at": Fallback.TRUTHY,
    "max_price": Fallback.TRUTHY,
    "min_price": Fallback.TRUTHY,
    "rating": Fallback.TRUTHY,
    "availability": Fallback.TRUTHY,
    "condition": Fallback.TRUTHY,
    "date_listed": Fallback.TRUTHY,
    "delivery_method": Fallback.TRUTHY,
    "category": Fallback.TRUTHY,
    "sort_by": Fallback.TRUTHY,
}

# use sites that deviate from COMMON_OPTION_FALLBACK
SITE_FALLBACK: Dict[Tuple[str, str], Fallback] = {
    ("ai_prompt", "min_price"): Fallback.ITEM_ONLY,
    ("ai_prompt", "max_price"): Fallback.ITEM_ONLY,
}


def resolve_option(key: str, item: Any, marketplace: Any, site: str = "search") -> Any:
    """Value of a common option for an item, falling back to its marketplace."""
    rule = SITE_FALLBACK.get((site, key), COMMON_OPTION_FALLBACK[key])
    value = getattr(item, key)
    if rule is Fallback.ITEM_ONLY:
        return value
    if rule is Fallback.NOT_NONE:
        return value if value is not None else getattr(marketplace, key)
    return value or getattr(marketplace, key)
```

(`marketplace.py` already imports `Enum`, `Dict`, `Any`; add any that are missing.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_resolve_option.py -v`
Expected: PASS.

- [ ] **Step 5: Switch `facebook.py` call sites**

Import: `from .marketplace import ItemConfig, Marketplace, MarketplaceConfig, WebPage, resolve_option`.

In `search`, replace each block as follows (keep surrounding code and comments):

```python
        condition = resolve_option("condition", item_config, self.config)
```

```python
        date_listed_values = resolve_option("date_listed", item_config, self.config)
        date_listed = (
            date_listed_values[0 if item_config.searched_count == 0 else -1]
            if date_listed_values
            else DateListed.ANYTIME.value
        )
```

```python
        delivery_values = resolve_option("delivery_method", item_config, self.config)
        delivery_method = (
            delivery_values[0 if item_config.searched_count == 0 else -1]
            if delivery_values
            else DeliveryMethod.ALL.value
        )
```

```python
        availability_values = resolve_option("availability", item_config, self.config)
        availability = (
            availability_values[0 if item_config.searched_count == 0 else -1]
            if availability_values
            else Availability.ALL.value
        )
```

```python
        sort_by = resolve_option("sort_by", item_config, self.config)
```

```python
        search_city = resolve_option("search_city", item_config, self.config) or []
        city_name = resolve_option("city_name", item_config, self.config) or []
        radiuses = resolve_option("radius", item_config, self.config)
        currencies = resolve_option("currency", item_config, self.config)
```

```python
            max_price = resolve_option("max_price", item_config, self.config)
```

```python
            min_price = resolve_option("min_price", item_config, self.config)
```

```python
            category = resolve_option("category", item_config, self.config)
```

In `check_listing`:

```python
        # get locations from either marketplace config or item config
        allowed_locations = resolve_option("seller_locations", item_config, self.config) or []
```

```python
        # get exclude_sellers from both item_config or config
        exclude_sellers = resolve_option("exclude_sellers", item_config, self.config) or []
```

- [ ] **Step 6: Switch `monitor.py` call sites**

Import: `from .marketplace import Marketplace, TItemConfig, TMarketplaceConfig, resolve_option`.

Lines 171-173 and 729-733 (both `users_to_notify` assignments):

```python
        users_to_notify = resolve_option("notify", item_config, marketplace_config) or list(
            self.config.user.keys()
        )
```

(indent the second one to match its block.) Lines 232-241:

```python
            rating_values = resolve_option("rating", item_config, marketplace_config)
            acceptable_rating = (
                rating_values[0 if item_config.searched_count == 0 else -1]
                if rating_values
                else 3
            )
```

Line 362:

```python
                    start_at_list = resolve_option("start_at", item_config, marketplace_config)
```

Lines 389-399:

```python
                        search_interval = max(
                            resolve_option("search_interval", item_config, marketplace_config)
                            or 30 * 60,
                            1,
                        )
                        max_search_interval = max(
                            resolve_option("max_search_interval", item_config, marketplace_config)
                            or 60 * 60,
                            search_interval,
                        )
```

Lines 771-776:

```python
        ai_agents = resolve_option("ai", item_config, marketplace_config)
```

- [ ] **Step 7: Switch `ai.py` call sites**

Import: `from .marketplace import TItemConfig, TMarketplaceConfig, resolve_option`.

```python
        max_price = (
            resolve_option("max_price", item_config, marketplace_config, site="ai_prompt") or 0
        )
        min_price = (
            resolve_option("min_price", item_config, marketplace_config, site="ai_prompt") or 0
        )
```

```python
        # prompt
        custom_prompt = resolve_option("prompt", item_config, marketplace_config)
        if custom_prompt is not None:
            prompt += custom_prompt
        else:
            prompt += (
                "Evaluate how well this listing matches the user's criteria. Assess the description, MSRP, model year, "
                "condition, and seller's credibility."
            )
        # extra_prompt
        prompt += "\n"
        extra_prompt = resolve_option("extra_prompt", item_config, marketplace_config)
        if extra_prompt is not None:
            prompt += f"\n{extra_prompt.strip()}\n"
        # rating_prompt
        rating_prompt = resolve_option("rating_prompt", item_config, marketplace_config)
        if rating_prompt is not None:
            prompt += f"\n{rating_prompt.strip()}\n"
        else:
```

(the `else:` keeps the existing default rating text block unchanged.)

- [ ] **Step 8: Run all tests and static checks**

Run: `uv run pytest tests/test_option_fallback.py tests/test_resolve_option.py -v && uv run pytest -q && uv run ruff check src tests && uv run mypy src`
Expected: all PASS, no lint or type errors. Then `grep -n "or self.config\.\|or marketplace_config\.\|marketplace_config\.\(ai\|notify\|rating\|prompt\|extra_prompt\|rating_prompt\|start_at\)\b" src/ai_marketplace_monitor/{facebook,monitor,ai}.py` must print no line that reads a key of `COMMON_OPTION_FALLBACK`; any remaining hit must be an unrelated attribute (e.g. `marketplace_config.name`).

- [ ] **Step 9: Commit**

```bash
git add src/ai_marketplace_monitor/marketplace.py src/ai_marketplace_monitor/facebook.py src/ai_marketplace_monitor/monitor.py src/ai_marketplace_monitor/ai.py tests/test_resolve_option.py
git commit -m "refactor: resolve item/marketplace options through resolve_option (#362)"
```

---

### Task 6: `normalize` package — model, ordering, change descriptions

**Files:**
- Modify: `src/ai_marketplace_monitor/utils.py` (add `is_sensitive_key`)
- Modify: `src/ai_marketplace_monitor/webui/secrets_redact.py:37-69` (use it)
- Create: `src/ai_marketplace_monitor/normalize/__init__.py`, `src/ai_marketplace_monitor/normalize/model.py`
- Test: `tests/test_normalize_model.py`

**Interfaces:**
- Produces (`ai_marketplace_monitor.utils`): `is_sensitive_key(key: str) -> bool`.
- Produces (`ai_marketplace_monitor.normalize.model`):
  - `NormalizeError(ValueError)`
  - `@dataclass Change(section: str, action: str, key: str | None, detail: str)`
  - `@dataclass NormalizeResult(config: Dict[str, Any], changes: List[Change])`
  - `SECTION_ORDER: Tuple[str, ...]`, `COMMON_OPTIONS: Tuple[str, ...]`, `LOCATION_KEYS: Tuple[str, ...]`, `AI_PROMPT_ITEM_ONLY: Tuple[str, ...]`, `MASK = "<REDACTED>"`
  - `mask(key: str | None, value: Any) -> Any`
  - `order_config(cfg: Dict[str, Any]) -> Dict[str, Any]`
  - `describe_changes(before: Dict[str, Any], after: Dict[str, Any], notes: Dict[Tuple[str, str | None], str] | None = None) -> List[Change]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_normalize_model.py
from ai_marketplace_monitor.normalize.model import (
    COMMON_OPTIONS,
    Change,
    describe_changes,
    order_config,
)
from ai_marketplace_monitor.utils import is_sensitive_key
from tests.normalize_util import dumps


def test_is_sensitive_key() -> None:
    assert is_sensitive_key("smtp_password")
    assert is_sensitive_key("telegram_token")
    assert is_sensitive_key("username")
    assert not is_sensitive_key("email")


def test_common_options_include_facebook_and_generic_options() -> None:
    assert {"notify", "ai", "search_region", "sort_by", "seller_locations"} <= set(COMMON_OPTIONS)
    assert "search_phrases" not in COMMON_OPTIONS
    assert "username" not in COMMON_OPTIONS


def test_type_order_is_fixed_and_within_type_order_kept() -> None:
    cfg = {
        "item": {"zeta": {"search_phrases": "z"}, "alpha": {"search_phrases": "a"}},
        "user": {"u": {"email": "e"}},
        "marketplace": {"facebook": {}},
    }
    out = order_config(cfg)
    assert list(out) == ["marketplace", "user", "item"]
    assert list(out["item"]) == ["zeta", "alpha"]


def test_key_order_request_enabled_then_declared_fields() -> None:
    cfg = {
        "item": {
            "bike": {
                "description": "d",
                "search_phrases": "bike",
                "enabled": True,
                "request": "r",
                "notify": ["u"],
            }
        }
    }
    item = order_config(cfg)["item"]["bike"]
    assert list(item) == ["request", "enabled", "notify", "search_phrases", "description"]


def test_monitor_is_a_flat_section() -> None:
    out = order_config({"monitor": {"proxy_bypass": "x", "request": "r"}})
    assert list(out["monitor"]) == ["request", "proxy_bypass"]


def test_translation_settings_first_then_words_in_input_order() -> None:
    cfg = {
        "translation": {
            "de": {"Details": "Details", "Condition": "Zustand", "locale": "de_DE", "request": "r"}
        }
    }
    assert list(order_config(cfg)["translation"]["de"]) == [
        "request",
        "locale",
        "Details",
        "Condition",
    ]


def test_describe_changes_reports_set_remove_add_and_masks_secrets() -> None:
    before = {"user": {"u": {"email": "e", "smtp_password": "old"}}}
    after = {
        "user": {"u": {"email": "e2", "smtp_password": "new"}},
        "notification": {"email": {"smtp_server": "s"}},
    }
    changes = describe_changes(before, after)
    assert Change("user.u", "set", "email", "email: 'e' -> 'e2'") in changes
    assert Change("user.u", "set", "smtp_password", "smtp_password: '<REDACTED>' -> '<REDACTED>'") in changes
    assert Change("notification.email", "add", None, "new section") in changes


def test_describe_changes_reports_pure_reordering() -> None:
    before = {"item": {"b": {"search_phrases": "x", "notify": ["u"]}}}
    after = {"item": {"b": {"notify": ["u"], "search_phrases": "x"}}}
    assert dumps(before) != dumps(after)
    assert describe_changes(before, after) == [
        Change("*", "set", None, "reordered sections and keys")
    ]


def test_describe_changes_uses_notes() -> None:
    changes = describe_changes(
        {"item": {"b": {}}}, {"item": {"b": {"notify": ["u"]}}}, {("item.b", "notify"): "why"}
    )
    assert changes == [Change("item.b", "set", "notify", "why")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_normalize_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ai_marketplace_monitor.normalize'`.

- [ ] **Step 3: Move `is_sensitive_key` to `utils.py`**

Append to `utils.py`:

```python
# Key names treated as sensitive. Case-insensitive substring match,
# applied to the TOML key (e.g. ``pushbullet_token`` matches ``token``).
_SENSITIVE_SUBSTRINGS = ("password", "token", "api_key", "secret")
# Exact-match keys that don't contain one of the substrings above but
# are still sensitive (identifiers that reveal the user's identity).
_SENSITIVE_EXACT = {"username", "api_secret"}


def is_sensitive_key(key: str) -> bool:
    """Whether a config key holds a secret that must never be displayed."""
    k = key.lower()
    return k in _SENSITIVE_EXACT or any(s in k for s in _SENSITIVE_SUBSTRINGS)
```

In `webui/secrets_redact.py`, delete `_SENSITIVE_SUBSTRINGS`, `_SENSITIVE_EXACT`, and the body of `_is_sensitive`, replacing them with:

```python
from ..utils import is_sensitive_key as _is_sensitive
```

(placed with the other imports; keep every existing call to `_is_sensitive`.)

- [ ] **Step 4: Create the package**

```python
# src/ai_marketplace_monitor/normalize/__init__.py
"""Config normalization: canonical form for AI editing, compact form for people."""

from .model import Change, NormalizeError, NormalizeResult

__all__ = ["Change", "NormalizeError", "NormalizeResult"]
```

```python
# src/ai_marketplace_monitor/normalize/model.py
"""Shared types, constants, ordering, and change descriptions for normalization."""

import json
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional, Tuple

from ..ai import AIConfig
from ..facebook import FacebookItemConfig, FacebookMarketItemCommonConfig, FacebookMarketplaceConfig
from ..marketplace import SITE_FALLBACK, MarketItemCommonConfig
from ..region import RegionConfig
from ..user import UserConfig
from ..utils import BaseConfig, MonitorConfig, TranslationConfig, is_sensitive_key

SECTION_ORDER: Tuple[str, ...] = (
    "monitor",
    "ai",
    "marketplace",
    "user",
    "notification",
    "region",
    "item",
    "translation",
)
_BASE_FIELDS = {f.name for f in fields(BaseConfig)}
COMMON_OPTIONS: Tuple[str, ...] = tuple(
    dict.fromkeys(
        f.name
        for cls in (MarketItemCommonConfig, FacebookMarketItemCommonConfig)
        for f in fields(cls)
        if f.name not in _BASE_FIELDS
    )
)
LOCATION_KEYS: Tuple[str, ...] = ("search_region", "search_city", "city_name", "radius", "currency")
AI_PROMPT_ITEM_ONLY: Tuple[str, ...] = tuple(k for (site, k) in SITE_FALLBACK if site == "ai_prompt")
MASK = "<REDACTED>"

# dataclass fields that never appear as config keys (runtime state, or the
# translation `dictionary`, whose entries are the section's remaining keys)
_RUNTIME_FIELDS = {"searched_count", "monitor_config", "dictionary"}
_FIELD_ORDER: Dict[str, List[str]] = {
    section: [f.name for f in fields(cls) if f.name not in _RUNTIME_FIELDS]
    for section, cls in {
        "monitor": MonitorConfig,
        "ai": AIConfig,
        "marketplace": FacebookMarketplaceConfig,
        "user": UserConfig,
        # notification sections hold a subset of UserConfig fields
        "notification": UserConfig,
        "region": RegionConfig,
        "item": FacebookItemConfig,
        "translation": TranslationConfig,
    }.items()
}


class NormalizeError(ValueError):
    """Normalization is impossible or would change runtime behavior."""


@dataclass
class Change:
    section: str  # e.g. "user.alice", "notification.email", "*" for whole-file
    action: str  # "add" | "move" | "set" | "remove"
    key: Optional[str]
    detail: str


@dataclass
class NormalizeResult:
    config: Dict[str, Any]
    changes: List[Change] = field(default_factory=list)


def mask(key: Optional[str], value: Any) -> Any:
    return MASK if key is not None and is_sensitive_key(key) else value


def _order_section(section_type: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    declared = _FIELD_ORDER.get(section_type)
    if declared is None:
        return dict(raw)
    out: Dict[str, Any] = {k: raw[k] for k in ("request", "enabled") if k in raw}
    out.update({k: raw[k] for k in declared if k in raw and k not in out})
    out.update({k: v for k, v in raw.items() if k not in out})
    return out


def order_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fixed type order, input order within a type, canonical key order within a section."""
    out: Dict[str, Any] = {}
    for section_type in [*SECTION_ORDER, *(t for t in cfg if t not in SECTION_ORDER)]:
        if section_type not in cfg:
            continue
        body = cfg[section_type]
        if section_type == "monitor":
            out[section_type] = _order_section("monitor", body)
        else:
            out[section_type] = {n: _order_section(section_type, s) for n, s in body.items()}
    return out


def _sections(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for section_type, body in cfg.items():
        if section_type == "monitor":
            out["monitor"] = body
        else:
            out.update({f"{section_type}.{n}": s for n, s in body.items()})
    return out


_MISSING = object()


def _key_changes(
    label: str,
    old: Dict[str, Any],
    new: Dict[str, Any],
    notes: Dict[Tuple[str, Optional[str]], str],
) -> List[Change]:
    changes = []
    for key in [*old, *(k for k in new if k not in old)]:
        old_value, new_value = old.get(key, _MISSING), new.get(key, _MISSING)
        if old_value == new_value:
            continue
        if new_value is _MISSING:
            action, detail = "remove", f"removed {key}"
        elif old_value is _MISSING:
            action, detail = "set", f"{key} = {mask(key, new_value)!r}"
        else:
            action = "set"
            detail = f"{key}: {mask(key, old_value)!r} -> {mask(key, new_value)!r}"
        changes.append(Change(label, action, key, notes.get((label, key), detail)))
    return changes


def describe_changes(
    before: Dict[str, Any],
    after: Dict[str, Any],
    notes: Optional[Dict[Tuple[str, Optional[str]], str]] = None,
) -> List[Change]:
    """Human-readable list of differences between two raw configs (secrets masked)."""
    notes = notes or {}
    old_sections, new_sections = _sections(before), _sections(after)
    changes: List[Change] = []
    for label in [*old_sections, *(k for k in new_sections if k not in old_sections)]:
        if label not in old_sections:
            changes.append(Change(label, "add", None, notes.get((label, None), "new section")))
        elif label not in new_sections:
            detail = notes.get((label, None), "section removed")
            changes.append(Change(label, "remove", None, detail))
        else:
            changes.extend(
                _key_changes(label, old_sections[label], new_sections[label], notes)
            )
    if not changes and json.dumps(before, default=str) != json.dumps(after, default=str):
        changes.append(Change("*", "set", None, "reordered sections and keys"))
    return changes
```

- [ ] **Step 5: Run tests and checks**

Run: `uv run pytest tests/test_normalize_model.py tests/test_webui_secrets_redact.py -v && uv run pytest -q && uv run ruff check src tests && uv run mypy src`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai_marketplace_monitor/utils.py src/ai_marketplace_monitor/webui/secrets_redact.py src/ai_marketplace_monitor/normalize tests/test_normalize_model.py
git commit -m "feat(normalize): add model, ordering, and change descriptions (#362)"
```

---

### Task 7: `effective_view` and `check_equivalent`

**Files:**
- Create: `src/ai_marketplace_monitor/normalize/effective.py`
- Modify: `src/ai_marketplace_monitor/normalize/__init__.py`
- Test: `tests/test_normalize_effective.py`

**Interfaces:**
- Consumes: `Config.from_dicts` (Task 3), `resolve_option` (Task 5), `COMMON_OPTIONS`, `AI_PROMPT_ITEM_ONLY`, `NormalizeError`, `mask` (Task 6).
- Produces:
  - `effective_view(config: Config) -> Dict[str, Any]` with keys `"marketplace"`, `"ai"`, `"monitor"`, `"translation"` (enabled translations: `locale`, `dictionary`), `"item"`; each `view["item"][name]` holds `"marketplace"`, `"enabled"`, `"search_phrases"`, `"keywords"`, `"antikeywords"`, `"description"`, every common option except `search_region`/`notify`/`ai`, `"ai_prompt:min_price"`, `"ai_prompt:max_price"`, `"notify"` (dict user → user view), `"ai"` (list).
  - `check_equivalent(system_cfg: Dict[str, Any], before: Dict[str, Any], after: Dict[str, Any]) -> List[str]` — returns the allowed differing paths (dotted strings); raises `NormalizeError` otherwise.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_normalize_effective.py
import copy

import pytest

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.normalize import NormalizeError, check_equivalent, effective_view
from tests.normalize_util import parse, system_cfg

BASE = """
[ai.openai]
api_key = "sk-test"

[marketplace.facebook]
search_city = "houston"
max_price = "300"

[user.alice]
email = "alice@example.com"
smtp_password = "s3cret"

[user.bob]
pushbullet_token = "abc"

[item.bike]
search_phrases = "bike"
"""


def test_effective_view_resolves_defaults() -> None:
    view = effective_view(Config.from_dicts(system_cfg(), parse(BASE)))
    bike = view["item"]["bike"]
    assert bike["marketplace"] == "facebook"
    assert bike["search_city"] == ["houston"]
    assert set(bike["notify"]) == {"alice", "bob"}
    assert bike["ai"] == ["openai"]
    assert bike["max_price"] == "300"
    assert bike["ai_prompt:max_price"] is None
    assert "name" not in bike["notify"]["alice"]
    assert bike["notify"]["alice"]["email"] == ["alice@example.com"]


def test_identical_configs_are_equivalent() -> None:
    assert check_equivalent(system_cfg(), parse(BASE), parse(BASE)) == []


def test_behavior_change_raises_with_path() -> None:
    after = parse(BASE)
    after["item"]["bike"]["notify"] = ["alice"]
    with pytest.raises(NormalizeError, match=r"item\.bike\.notify"):
        check_equivalent(system_cfg(), parse(BASE), after)


def test_secret_values_are_masked_in_errors() -> None:
    after = parse(BASE)
    after["user"]["alice"]["smtp_password"] = "other-secret"
    with pytest.raises(NormalizeError) as info:
        check_equivalent(system_cfg(), parse(BASE), after)
    assert "s3cret" not in str(info.value)
    assert "other-secret" not in str(info.value)
    assert "<REDACTED>" in str(info.value)


def test_ai_prompt_price_difference_is_allowed_when_it_matches_search() -> None:
    after = parse(BASE)
    after["item"]["bike"]["max_price"] = "300"
    allowed = check_equivalent(system_cfg(), parse(BASE), after)
    assert allowed == ["item.bike.ai_prompt:max_price"]


def test_ai_prompt_price_difference_not_matching_search_raises() -> None:
    after = parse(BASE)
    after["item"]["bike"]["max_price"] = "250"
    with pytest.raises(NormalizeError):
        check_equivalent(system_cfg(), parse(BASE), after)


def test_invalid_after_config_raises() -> None:
    after = copy.deepcopy(parse(BASE))
    after["item"]["bike"]["search_city"] = "Not Valid"
    with pytest.raises(NormalizeError, match="does not load"):
        check_equivalent(system_cfg(), parse(BASE), after)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_normalize_effective.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_equivalent'`.

- [ ] **Step 3: Implement**

```python
# src/ai_marketplace_monitor/normalize/effective.py
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
        "ai": {n: {k: v for k, v in asdict(a).items() if k != "request"} for n, a in config.ai.items()},
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


def _format(path: KeyPath, old: Any, new: Any) -> str:
    key = next((p for p in reversed(path) if mask(p, "x") != "x"), path[-1])
    return f"{'.'.join(path)}: {mask(key, old)!r} -> {mask(key, new)!r}"


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
```

Update `normalize/__init__.py`:

```python
"""Config normalization: canonical form for AI editing, compact form for people."""

from .effective import check_equivalent, effective_view
from .model import Change, NormalizeError, NormalizeResult

__all__ = ["Change", "NormalizeError", "NormalizeResult", "check_equivalent", "effective_view"]
```

`_format` masks the value when any path component is a sensitive key (e.g. `item.bike.notify.alice.smtp_password`).

- [ ] **Step 4: Run tests and checks**

Run: `uv run pytest tests/test_normalize_effective.py -v && uv run pytest -q && uv run ruff check src tests && uv run mypy src`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_marketplace_monitor/normalize tests/test_normalize_effective.py
git commit -m "feat(normalize): add effective_view and check_equivalent (#362)"
```

---

### Task 8: Canonical users and notification sections

**Files:**
- Create: `src/ai_marketplace_monitor/normalize/notifications.py`
- Test: `tests/test_normalize_notifications.py`

**Interfaces:**
- Consumes: loaded `Config` (`.user`, `.notification`), `check_equivalent` (tests only).
- Produces: `normalize_notifications(cfg: Dict[str, Any], loaded: Config) -> None` — rewrites `cfg["user"]` and `cfg["notification"]` in place per spec "Users and notifications"; `TYPE_CLASSES`, `COMMON_FIELDS`, `RECIPIENT_FIELDS`, `CHANNEL_FIELDS`.

- [ ] **Step 1: Write the failing tests**

Each test runs the step on a copy, then asserts the expected layout **and** that `check_equivalent` passes against the input.

```python
# tests/test_normalize_notifications.py
import copy
from typing import Any, Dict

import pytest

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.normalize import check_equivalent
from ai_marketplace_monitor.normalize.notifications import normalize_notifications
from tests.normalize_util import parse, system_cfg

HEAD = """
[marketplace.facebook]
search_city = "houston"

[item.bike]
search_phrases = "bike"
"""


def _run(text: str) -> Dict[str, Any]:
    raw = parse(HEAD + text)
    cfg = copy.deepcopy(raw)
    normalize_notifications(cfg, Config.from_dicts(system_cfg(), raw))
    check_equivalent(system_cfg(), raw, cfg)
    return cfg


def test_inline_single_user_is_split() -> None:
    cfg = _run("""
    [user.alice]
    email = "alice@example.com"
    smtp_server = "smtp.example.com"
    smtp_password = "pw"
    """)
    assert cfg["user"]["alice"] == {"email": "alice@example.com", "notify_with": ["email"]}
    assert cfg["notification"]["email"] == {"smtp_server": "smtp.example.com", "smtp_password": "pw"}


def test_shared_smtp_with_per_user_email_keeps_section() -> None:
    cfg = _run("""
    [user.alice]
    email = "alice@example.com"
    notify_with = "gmail"

    [user.bob]
    email = "bob@example.com"
    notify_with = "gmail"

    [notification.gmail]
    smtp_username = "me@gmail.com"
    smtp_password = "pw"
    """)
    assert cfg["notification"] == {"gmail": {"smtp_username": "me@gmail.com", "smtp_password": "pw"}}
    assert cfg["user"]["alice"]["notify_with"] == ["gmail"]
    assert cfg["user"]["bob"] == {"email": "bob@example.com", "notify_with": ["gmail"]}


def test_group_chat_id_moves_to_users() -> None:
    cfg = _run("""
    [user.alice]
    notify_with = "tg"

    [user.bob]
    notify_with = "tg"

    [notification.tg]
    telegram_token = "123:abc"
    telegram_chat_id = "-100"
    """)
    assert cfg["notification"]["tg"] == {"telegram_token": "123:abc"}
    assert cfg["user"]["alice"] == {"telegram_chat_id": "-100", "notify_with": ["tg"]}


def test_notify_with_unset_means_all_sections() -> None:
    cfg = _run("""
    [user.alice]
    email = "alice@example.com"

    [notification.gmail]
    smtp_password = "pw"

    [notification.tg]
    telegram_token = "123:abc"
    telegram_chat_id = "1"
    """)
    assert cfg["user"]["alice"]["notify_with"] == ["gmail", "tg"]


def test_notify_with_empty_list_means_none() -> None:
    cfg = _run("""
    [user.alice]
    email = "alice@example.com"
    notify_with = []

    [notification.gmail]
    smtp_password = "pw"
    """)
    assert cfg["user"]["alice"] == {"email": "alice@example.com", "notify_with": []}
    assert cfg["notification"]["gmail"] == {"smtp_password": "pw"}


def test_inline_value_shadowed_by_section_default_is_dropped() -> None:
    cfg = _run("""
    [user.alice]
    email = "alice@example.com"
    max_retries = 3
    notify_with = "gmail"

    [notification.gmail]
    smtp_password = "pw"
    """)
    assert "max_retries" not in cfg["user"]["alice"]
    assert "max_retries" not in cfg["notification"]["gmail"]


def test_inline_common_value_without_sections_moves_into_channel_section() -> None:
    cfg = _run("""
    [user.alice]
    pushbullet_token = "abc"
    max_retries = 3
    """)
    assert cfg["notification"]["pushbullet"] == {"max_retries": 3, "pushbullet_token": "abc"}
    assert cfg["user"]["alice"] == {"notify_with": ["pushbullet"]}


def test_same_type_later_section_wins() -> None:
    cfg = _run("""
    [user.alice]
    telegram_chat_id = "1"
    notify_with = ["tg1", "tg2"]

    [notification.tg1]
    telegram_token = "1:a"

    [notification.tg2]
    telegram_token = "2:b"
    """)
    assert cfg["user"]["alice"]["notify_with"] == ["tg2"]
    assert cfg["notification"]["tg1"] == {"telegram_token": "1:a"}  # leftover kept
    assert cfg["notification"]["tg2"] == {"telegram_token": "2:b"}


def test_disabled_and_unused_sections_are_kept() -> None:
    cfg = _run("""
    [user.alice]
    pushbullet_token = "abc"
    notify_with = []

    [notification.old]
    enabled = false
    pushover_user_key = "k"
    pushover_api_token = "t"
    """)
    assert cfg["notification"]["old"] == {
        "enabled": False,
        "pushover_user_key": "k",
        "pushover_api_token": "t",
    }


def test_unset_placeholder_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIMM_TEST_UNSET_TOKEN", raising=False)
    cfg = _run("""
    [user.alice]
    notify_with = "tg"

    [notification.tg]
    telegram_token = "${AIMM_TEST_UNSET_TOKEN}"
    telegram_chat_id = "1"
    """)
    assert cfg["notification"]["tg"] == {"telegram_token": "${AIMM_TEST_UNSET_TOKEN}"}
    assert cfg["user"]["alice"]["telegram_chat_id"] == "1"


def test_user_request_stays_and_section_request_is_kept_on_claim() -> None:
    cfg = _run("""
    [user.alice]
    request = "alice wants telegram"
    notify_with = "tg"

    [notification.tg]
    request = "our bot"
    telegram_token = "123:abc"
    telegram_chat_id = "1"
    """)
    assert cfg["user"]["alice"]["request"] == "alice wants telegram"
    assert cfg["notification"]["tg"] == {"request": "our bot", "telegram_token": "123:abc"}


def test_type_name_taken_by_leftover_falls_back_to_user_suffix() -> None:
    cfg = _run("""
    [user.alice]
    pushbullet_token = "abc"
    notify_with = []

    [notification.pushbullet]
    enabled = false
    pushbullet_token = "zzz"
    """)
    # alice's inline token has notify_with = [] so it is never sent; still preserved
    assert cfg["notification"]["pushbullet_alice"] == {"pushbullet_token": "abc"}
    assert cfg["user"]["alice"]["notify_with"] == ["pushbullet_alice"]
```

> Note on the last test: `notify_with = []` with an inline token means no notification sections are merged, but the inline token is still part of alice's effective `UserConfig` (and `notify_all` instantiates every notifier from user fields), so the canonical form must keep it reachable. The step therefore always lists a user's own channel sections in `notify_with`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_normalize_notifications.py -v`
Expected: FAIL — `ModuleNotFoundError: ... normalize.notifications`.

- [ ] **Step 3: Implement**

```python
# src/ai_marketplace_monitor/normalize/notifications.py
"""Canonical layout for users and [notification.*] sections."""

import json
from dataclasses import MISSING, fields
from typing import Any, Dict, List, Set, Tuple, Type

from ..config import Config
from ..email_notify import EmailNotificationConfig
from ..notification import NotificationConfig, PushNotificationConfig
from ..ntfy import NtfyNotificationConfig
from ..pushbullet import PushbulletNotificationConfig
from ..pushover import PushoverNotificationConfig
from ..telegram import TelegramNotificationConfig
from ..user import UserConfig

TYPE_CLASSES: Dict[str, Type[NotificationConfig]] = {
    "email": EmailNotificationConfig,
    "pushbullet": PushbulletNotificationConfig,
    "pushover": PushoverNotificationConfig,
    "ntfy": NtfyNotificationConfig,
    "telegram": TelegramNotificationConfig,
}
_BASE_FIELDS = {"name", "enabled", "request"}
COMMON_FIELDS: Tuple[str, ...] = tuple(
    f.name
    for f in fields(PushNotificationConfig)
    if f.name not in _BASE_FIELDS and not f.name.startswith("_")
)
RECIPIENT_FIELDS: Tuple[str, ...] = ("email", "telegram_chat_id", "pushover_user_key", "ntfy_topic")
CHANNEL_FIELDS: Dict[str, Tuple[str, ...]] = {
    t: tuple(
        f.name
        for f in fields(cls)
        if f.name not in _BASE_FIELDS
        and f.name not in COMMON_FIELDS
        and f.name not in RECIPIENT_FIELDS
        and not f.name.startswith("_")
    )
    for t, cls in TYPE_CLASSES.items()
}
_USER_KEPT_FIELDS = ("enabled", "request", "remind")
_MERGE_SKIPPED = ("type", "name", "request")


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("${") and value.endswith("}")


def _sources(user_raw: Dict[str, Any], notif_raw: Dict[str, Any]) -> List[str]:
    """Notification sections merged into this user at runtime, in merge order."""
    notify_with = user_raw.get("notify_with")
    if notify_with is None:
        names = list(notif_raw)
    else:
        names = [notify_with] if isinstance(notify_with, str) else list(notify_with)
    return [n for n in names if notif_raw[n].get("enabled") is not False]


def _provenance(
    user_raw: Dict[str, Any],
    sources: List[str],
    notif_raw: Dict[str, Any],
    loaded: Dict[str, NotificationConfig],
) -> Dict[str, Any]:
    """Raw value from the source that wins each field (None when a default wins).

    Mirrors Config.expand_notifications: every non-None field of each source's
    loaded instance, defaults included, overrides what came before.
    """
    winners = dict(user_raw)
    for name in sources:
        raw = notif_raw[name]
        for key, value in vars(loaded[name]).items():
            if key in _MERGE_SKIPPED:
                continue
            placeholder = _is_placeholder(raw.get(key)) and winners.get(key) is None
            if value is None and not placeholder:
                continue
            winners[key] = raw.get(key)
    return winners


def _default(cls: Type[Any], name: str) -> Any:
    for f in fields(cls):
        if f.name == name:
            if f.default is not MISSING:
                return f.default
            if f.default_factory is not MISSING:
                return f.default_factory()
    return None


def _loaded_class(content: Dict[str, Any]) -> Type[Any]:
    instance = NotificationConfig.get_config(name="_", **content)
    return type(instance) if instance is not None else UserConfig


def _declares(cls: Type[Any], name: str) -> bool:
    return any(f.name == name for f in fields(cls))


def _plan_user(
    user_raw: Dict[str, Any], winners: Dict[str, Any], effective: UserConfig
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Canonical user section and per-type channel sections for one user."""
    user = {k: user_raw[k] for k in _USER_KEPT_FIELDS if k in user_raw}
    user.update({f: winners[f] for f in RECIPIENT_FIELDS if winners.get(f) is not None})
    sections: Dict[str, Dict[str, Any]] = {}
    for section_type, channel_fields in CHANNEL_FIELDS.items():
        content = {f: winners[f] for f in channel_fields if winners.get(f) is not None}
        if content:
            sections[section_type] = content
    classes = {t: _loaded_class(c) for t, c in sections.items()}
    for section_type, content in sections.items():
        cls = classes[section_type]
        for f in COMMON_FIELDS:
            if not _declares(cls, f):
                continue
            if winners.get(f) is not None:
                content[f] = winners[f]
            elif getattr(effective, f) != _default(cls, f):
                content[f] = getattr(effective, f)
    for f in COMMON_FIELDS:
        placed = any(_declares(cls, f) for cls in classes.values())
        if not placed and winners.get(f) is not None:
            user[f] = winners[f]
    return user, sections


def _type_owners(sources: List[str], notif_raw: Dict[str, Any]) -> Dict[str, str]:
    """Existing section that supplied the winning channel fields of each type."""
    owners: Dict[str, str] = {}
    for name in sources:
        for section_type, channel_fields in CHANNEL_FIELDS.items():
            if any(f in notif_raw[name] for f in channel_fields):
                owners[section_type] = name
    return owners


def _name_groups(groups: Dict[str, Dict[str, Any]], notif_raw: Dict[str, Any]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    used: Set[str] = set()

    def free(name: str, group: Dict[str, Any]) -> bool:
        return name not in used and (name not in notif_raw or name in group["candidates"])

    for key, group in groups.items():
        base = f"{group['type']}_{group['users'][0]}"
        options = [*group["candidates"], group["type"], base]
        name = next((n for n in options if free(n, group)), None)
        suffix = 2
        while name is None:
            if free(f"{base}_{suffix}", group):
                name = f"{base}_{suffix}"
            suffix += 1
        names[key] = name
        used.add(name)
    return names


def normalize_notifications(cfg: Dict[str, Any], loaded: Config) -> None:
    """Rewrite cfg['user'] and cfg['notification'] into canonical form, in place."""
    notif_raw: Dict[str, Any] = cfg.get("notification", {})
    groups: Dict[str, Dict[str, Any]] = {}
    plans: Dict[str, Tuple[Dict[str, Any], List[str]]] = {}
    for user_name, user_raw in cfg.get("user", {}).items():
        sources = _sources(user_raw, notif_raw)
        winners = _provenance(user_raw, sources, notif_raw, loaded.notification)
        user, sections = _plan_user(user_raw, winners, loaded.user[user_name])
        owners = _type_owners(sources, notif_raw)
        keys = []
        for section_type, content in sections.items():
            key = f"{section_type}:{json.dumps(content, sort_keys=True, default=str)}"
            group = groups.setdefault(
                key, {"type": section_type, "content": content, "users": [], "candidates": []}
            )
            group["users"].append(user_name)
            owner = owners.get(section_type)
            if owner is not None and owner not in group["candidates"]:
                group["candidates"].append(owner)
            keys.append(key)
        plans[user_name] = (user, keys)

    names = _name_groups(groups, notif_raw)
    claimed = {name: key for key, name in names.items()}
    new_notifs: Dict[str, Any] = {}
    for name, raw in notif_raw.items():
        if name in claimed:
            kept = {k: raw[k] for k in ("request", "enabled") if k in raw}
            new_notifs[name] = {**kept, **groups[claimed[name]]["content"]}
        else:
            new_notifs[name] = raw
    for key, name in names.items():
        new_notifs.setdefault(name, groups[key]["content"])

    cfg["user"] = {
        u: {**user, "notify_with": [names[k] for k in keys]} for u, (user, keys) in plans.items()
    }
    if new_notifs:
        cfg["notification"] = new_notifs
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_normalize_notifications.py -v`
Expected: all PASS. If `check_equivalent` raises inside `_run` for a case, read its diff — it means the rules above miss a runtime quirk; fix `_provenance`/`_plan_user`, never loosen `check_equivalent`.

- [ ] **Step 5: Static checks and commit**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`

```bash
git add src/ai_marketplace_monitor/normalize/notifications.py tests/test_normalize_notifications.py
git commit -m "feat(normalize): canonical users and notification sections (#362)"
```

---

### Task 9: Push-down and `expand()`

**Files:**
- Create: `src/ai_marketplace_monitor/normalize/pushdown.py`, `src/ai_marketplace_monitor/normalize/core.py`
- Modify: `src/ai_marketplace_monitor/normalize/__init__.py`
- Test: `tests/test_normalize_pushdown.py`, `tests/test_normalize_properties.py`

**Interfaces:**
- Consumes: `normalize_notifications` (Task 8), `check_equivalent` (Task 7), `order_config`, `describe_changes`, `COMMON_OPTIONS`, `LOCATION_KEYS`, `AI_PROMPT_ITEM_ONLY` (Task 6), `COMMON_OPTION_FALLBACK`, `Fallback` (Task 5).
- Produces:
  - `bound_marketplace(item_raw: Dict[str, Any], marketplaces: Dict[str, Any]) -> str`
  - `push_down(cfg: Dict[str, Any]) -> Dict[Tuple[str, Optional[str]], str]` (in place; returns change notes)
  - `expand(user_cfg: Dict[str, Any], system_cfg: Dict[str, Any]) -> NormalizeResult`

- [ ] **Step 1: Write the failing push-down tests**

```python
# tests/test_normalize_pushdown.py
import pytest

from ai_marketplace_monitor.normalize import NormalizeError, expand
from tests.normalize_util import parse, system_cfg

USERS = """
[user.alice]
pushbullet_token = "a"

[user.bob]
pushbullet_token = "b"
"""


def _expand(text: str) -> dict:
    return expand(parse(text), system_cfg()).config


def test_common_options_move_into_items_and_lists_become_explicit() -> None:
    cfg = _expand(USERS + """
    [ai.openai]
    api_key = "sk-test"

    [marketplace.facebook]
    search_city = "houston"
    search_interval = "1h"
    username = "me"
    login_wait_time = 60

    [item.bike]
    search_phrases = "bike"
    """)
    assert cfg["marketplace"]["facebook"] == {"login_wait_time": 60, "username": "me"}
    bike = cfg["item"]["bike"]
    assert bike["search_city"] == "houston"
    assert bike["search_interval"] == "1h"
    assert bike["notify"] == ["alice", "bob"]
    assert bike["ai"] == ["openai"]


def test_no_ai_sections_means_no_ai_key() -> None:
    cfg = _expand(USERS + '[marketplace.facebook]\nsearch_city = "houston"\n[item.bike]\nsearch_phrases = "bike"\n')
    assert "ai" not in cfg["item"]["bike"]


def test_marketplace_empty_notify_means_all_users() -> None:
    cfg = _expand(USERS + '[marketplace.facebook]\nsearch_city = "houston"\nnotify = []\n[item.bike]\nsearch_phrases = "bike"\n')
    assert cfg["item"]["bike"]["notify"] == ["alice", "bob"]


def test_truthy_rule_replaces_empty_item_value() -> None:
    cfg = _expand(USERS + """
    [marketplace.facebook]
    search_city = "houston"
    notify = "alice"

    [item.bike]
    search_phrases = "bike"
    notify = []
    """)
    assert cfg["item"]["bike"]["notify"] == "alice"


def test_not_none_rule_keeps_empty_item_value() -> None:
    cfg = _expand(USERS + """
    [ai.openai]
    api_key = "sk-test"

    [marketplace.facebook]
    search_city = "houston"
    seller_locations = ["houston"]
    ai = ["openai"]

    [item.bike]
    search_phrases = "bike"
    seller_locations = []
    ai = []
    """)
    assert cfg["item"]["bike"]["seller_locations"] == []
    assert cfg["item"]["bike"]["ai"] == []


def test_marketplace_price_reaches_ai_prompt_and_is_reported() -> None:
    result = expand(parse(USERS + """
    [marketplace.facebook]
    search_city = "houston"
    max_price = "300"

    [item.bike]
    search_phrases = "bike"
    """), system_cfg())
    assert result.config["item"]["bike"]["max_price"] == "300"
    details = [c.detail for c in result.changes if c.key == "max_price" and c.section == "item.bike"]
    assert details and "AI prompt" in details[0]


def test_bundled_region_is_referenced_not_copied() -> None:
    cfg = _expand(USERS + '[marketplace.facebook]\nsearch_region = "usa"\n[item.bike]\nsearch_phrases = "bike"\n')
    assert cfg["item"]["bike"]["search_region"] == "usa"
    assert "region" not in cfg


def test_item_with_own_region_gets_no_location_keys() -> None:
    cfg = _expand(USERS + """
    [marketplace.facebook]
    search_city = "houston"
    radius = 50

    [item.bike]
    search_phrases = "bike"
    search_region = "usa"
    """)
    bike = cfg["item"]["bike"]
    assert "search_city" not in bike and "radius" not in bike


def test_own_city_inheriting_region_radius_raises() -> None:
    with pytest.raises(NormalizeError, match="bike"):
        _expand(USERS + """
        [marketplace.facebook]
        search_region = "usa"

        [item.bike]
        search_phrases = "bike"
        search_city = "dallas"
        """)


def test_item_binds_to_first_marketplace() -> None:
    cfg = _expand(USERS + """
    [marketplace.facebook]
    search_city = "houston"

    [marketplace.second]
    search_city = "dallas"

    [item.bike]
    search_phrases = "bike"
    """)
    assert cfg["item"]["bike"]["search_city"] == "houston"


def test_translation_passes_through() -> None:
    cfg = _expand(USERS + """
    [marketplace.facebook]
    search_city = "houston"

    [item.bike]
    search_phrases = "bike"

    [translation.de]
    locale = "de_DE"
    Condition = "Zustand"
    """)
    assert cfg["translation"] == {"de": {"locale": "de_DE", "Condition": "Zustand"}}


def test_invalid_input_raises() -> None:
    with pytest.raises(NormalizeError, match="not valid"):
        _expand(USERS + '[marketplace.facebook]\n[item.bike]\nsearch_phrases = "bike"\n')
```

- [ ] **Step 2: Write the failing property tests**

```python
# tests/test_normalize_properties.py
import copy
from typing import Any, Dict, List

import pytest

from ai_marketplace_monitor.config import load_config_dicts
from ai_marketplace_monitor.normalize import expand
from tests.normalize_util import EXAMPLES, dumps, parse, system_cfg

CASES: List[str] = [
    """
    [marketplace.facebook]
    search_city = "houston"
    search_interval = "30m"
    [user.alice]
    email = "alice@example.com"
    smtp_password = "pw"
    [item.bike]
    search_phrases = "bike"
    """,
    """
    [ai.openai]
    api_key = "sk-test"
    [marketplace.facebook]
    search_region = "usa"
    rating = [4, 3]
    notify = "alice"
    [user.alice]
    notify_with = "tg"
    [user.bob]
    email = "bob@example.com"
    [notification.tg]
    telegram_token = "123:abc"
    telegram_chat_id = "-100"
    [notification.gmail]
    smtp_password = "pw"
    [item.bike]
    search_phrases = "bike"
    [item.camera]
    search_phrases = ["gopro", "go pro"]
    notify = "bob"
    min_price = "100"
    """,
]


def _inputs() -> List[Dict[str, Any]]:
    return [parse(c) for c in CASES] + [load_config_dicts([p])[1] for p in EXAMPLES]


@pytest.mark.parametrize("user_cfg", _inputs())
def test_expand_is_idempotent_and_pure(user_cfg: Dict[str, Any]) -> None:
    before = copy.deepcopy(user_cfg)
    first = expand(user_cfg, system_cfg())
    assert user_cfg == before
    second = expand(first.config, system_cfg())
    assert second.changes == []
    assert dumps(second.config) == dumps(first.config)


def _shuffled(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for section_type in reversed(list(cfg)):
        body = cfg[section_type]
        if section_type == "monitor":
            out[section_type] = dict(reversed(list(body.items())))
        else:
            # keep section order within a type (it is behavior), reverse keys inside
            out[section_type] = {n: dict(reversed(list(s.items()))) for n, s in body.items()}
    return out


@pytest.mark.parametrize("user_cfg", _inputs())
def test_key_order_does_not_matter(user_cfg: Dict[str, Any]) -> None:
    a = expand(user_cfg, system_cfg()).config
    b = expand(_shuffled(user_cfg), system_cfg()).config
    assert dumps(a) == dumps(b)


def test_item_order_is_preserved() -> None:
    cfg = expand(parse(CASES[0] + '[item.alpha]\nsearch_phrases = "a"\n'), system_cfg()).config
    assert list(cfg["item"]) == ["bike", "alpha"]


def test_example_config_expands() -> None:
    result = expand(load_config_dicts([EXAMPLES[1]])[1], system_cfg())
    assert result.config["user"]["user1"]["notify_with"] == ["gmail", "pushbullet", "pushover"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_normalize_pushdown.py tests/test_normalize_properties.py -v`
Expected: FAIL — `ImportError: cannot import name 'expand'`.

- [ ] **Step 4: Implement push-down**

```python
# src/ai_marketplace_monitor/normalize/pushdown.py
"""Move common options from marketplaces into the items bound to them."""

import copy
from typing import Any, Dict, Optional, Tuple

from ..marketplace import COMMON_OPTION_FALLBACK, Fallback
from .model import AI_PROMPT_ITEM_ONLY, COMMON_OPTIONS, LOCATION_KEYS, NormalizeError

Notes = Dict[Tuple[str, Optional[str]], str]


def bound_marketplace(item_raw: Dict[str, Any], marketplaces: Dict[str, Any]) -> str:
    """Marketplace an item is searched in: its `marketplace` key, else the first one."""
    return item_raw.get("marketplace") or next(iter(marketplaces))


def _falls_back(key: str, item_raw: Dict[str, Any]) -> bool:
    if key not in item_raw:
        return True
    return COMMON_OPTION_FALLBACK.get(key) is Fallback.TRUTHY and not item_raw[key]


def _should_copy(key: str, item_raw: Dict[str, Any]) -> bool:
    if "search_region" in item_raw and key in LOCATION_KEYS:
        return False  # the item's own region provides all location keys
    if key == "search_region":
        return not item_raw.get("search_city")
    return _falls_back(key, item_raw)


def _check_location(
    item_name: str, item_raw: Dict[str, Any], market_name: str, market_raw: Dict[str, Any]
) -> None:
    if "search_region" not in market_raw or "search_region" in item_raw:
        return
    if not item_raw.get("search_city"):
        return
    missing = [k for k in ("radius", "currency") if _falls_back(k, item_raw)]
    if missing:
        keys = ", ".join(missing)
        raise NormalizeError(
            f"Item {item_name} sets its own search_city but inherits {keys} from the "
            f"search_region of marketplace {market_name}; set {keys} on the item "
            "or give it its own search_region."
        )


def push_down(cfg: Dict[str, Any]) -> Notes:
    """Make every item self-contained; return change notes keyed by (section, key)."""
    notes: Notes = {}
    markets: Dict[str, Any] = cfg.get("marketplace", {})
    users = list(cfg.get("user", {}))
    ais = list(cfg.get("ai", {}))
    for item_name, item in cfg.get("item", {}).items():
        label = f"item.{item_name}"
        market_name = bound_marketplace(item, markets)
        market = markets[market_name]
        _check_location(item_name, item, market_name, market)
        for key in COMMON_OPTIONS:
            if key in market and _should_copy(key, item):
                item[key] = copy.deepcopy(market[key])
                extra = " (now also used in the AI prompt)" if key in AI_PROMPT_ITEM_ONLY else ""
                notes[(label, key)] = f"{key} copied from marketplace.{market_name}{extra}"
        if not item.get("notify"):
            item["notify"] = list(users)
            notes[(label, "notify")] = "notify made explicit: all users"
        if "ai" not in item and ais:
            item["ai"] = list(ais)
            notes[(label, "ai")] = "ai made explicit: all AI backends"
    for market_name, market in markets.items():
        for key in COMMON_OPTIONS:
            if key in market:
                del market[key]
                notes[(f"marketplace.{market_name}", key)] = f"{key} moved into items"
    return notes
```

- [ ] **Step 5: Implement `expand()`**

```python
# src/ai_marketplace_monitor/normalize/core.py
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
```

Update `normalize/__init__.py`:

```python
"""Config normalization: expand() for AI editing (normalize() follows in Task 10)."""

from .core import expand
from .effective import check_equivalent, effective_view
from .model import Change, NormalizeError, NormalizeResult

__all__ = [
    "Change",
    "NormalizeError",
    "NormalizeResult",
    "check_equivalent",
    "effective_view",
    "expand",
]
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_normalize_pushdown.py tests/test_normalize_properties.py -v`
Expected: all PASS. A failure inside `check_equivalent` prints the exact differing path; fix the rule, not the check.

- [ ] **Step 7: Static checks and commit**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`

```bash
git add src/ai_marketplace_monitor/normalize tests/test_normalize_pushdown.py tests/test_normalize_properties.py
git commit -m "feat(normalize): push options into items and add expand() (#362)"
```

---

### Task 10: `compact()` and `normalize()`

`normalize(x)` = compact(expand(x)) is the only form ever written to disk; `compact` is an internal step that never runs on its own input without `expand` first.

**Files:**
- Create: `src/ai_marketplace_monitor/normalize/compact.py`
- Modify: `src/ai_marketplace_monitor/normalize/core.py` (add `normalize`), `src/ai_marketplace_monitor/normalize/__init__.py`, `tests/test_normalize_properties.py`
- Test: `tests/test_normalize_compact.py`

**Interfaces:**
- Consumes: `expand` (Task 9), `check_equivalent`, `order_config`, `describe_changes`, `bound_marketplace`, `Notes`, `COMMON_OPTIONS`, `LOCATION_KEYS`, `AI_PROMPT_ITEM_ONLY`.
- Produces:
  - `compact(expanded: Dict[str, Any]) -> Tuple[Dict[str, Any], Notes]` (internal; does not mutate its input; no validation of its own)
  - `normalize(user_cfg: Dict[str, Any], system_cfg: Dict[str, Any]) -> NormalizeResult` (public; changes reported relative to `user_cfg`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_normalize_compact.py
from ai_marketplace_monitor.normalize import normalize
from tests.normalize_util import parse, system_cfg

USERS = """
[user.alice]
pushbullet_token = "a"
"""


def _normalize(text: str) -> dict:
    return normalize(parse(USERS + text), system_cfg()).config


def test_hoists_values_shared_by_all_items() -> None:
    cfg = _normalize("""
    [marketplace.facebook]
    search_city = "houston"
    search_interval = "1h"

    [item.a]
    search_phrases = "a"

    [item.b]
    search_phrases = "b"
    """)
    assert cfg["marketplace"]["facebook"] == {
        "notify": ["alice"],
        "search_city": "houston",
        "search_interval": "1h",
    }
    assert cfg["item"]["a"] == {"search_phrases": "a"}


def test_differing_values_stay_on_items() -> None:
    cfg = _normalize("""
    [marketplace.facebook]
    search_city = "houston"

    [item.a]
    search_phrases = "a"
    search_interval = "1h"

    [item.b]
    search_phrases = "b"
    search_interval = "2h"
    """)
    assert "search_interval" not in cfg["marketplace"]["facebook"]
    assert cfg["item"]["b"]["search_interval"] == "2h"


def test_hand_written_marketplace_value_moves_down_when_an_item_differs() -> None:
    # disk always holds normalize() output, so a value shared by all but one item
    # does not stay on the marketplace with an override
    cfg = _normalize("""
    [marketplace.facebook]
    search_city = "houston"
    search_interval = "1h"

    [item.a]
    search_phrases = "a"

    [item.b]
    search_phrases = "b"
    search_interval = "2h"
    """)
    assert "search_interval" not in cfg["marketplace"]["facebook"]
    assert cfg["item"]["a"]["search_interval"] == "1h"


def test_single_item_is_not_hoisted() -> None:
    cfg = _normalize('[marketplace.facebook]\nsearch_city = "houston"\n[item.a]\nsearch_phrases = "a"\n')
    assert cfg["marketplace"]["facebook"] == {}
    assert cfg["item"]["a"]["search_city"] == "houston"


def test_disabled_item_blocks_hoist_when_it_differs() -> None:
    cfg = _normalize("""
    [marketplace.facebook]
    search_city = "houston"

    [item.a]
    search_phrases = "a"
    search_interval = "1h"

    [item.b]
    search_phrases = "b"
    search_interval = "1h"

    [item.c]
    enabled = false
    search_phrases = "c"
    search_interval = "3h"
    """)
    assert "search_interval" not in cfg["marketplace"]["facebook"]


def test_prices_never_hoisted() -> None:
    cfg = _normalize("""
    [marketplace.facebook]
    search_city = "houston"
    max_price = "300"

    [item.a]
    search_phrases = "a"

    [item.b]
    search_phrases = "b"
    """)
    assert "max_price" not in cfg["marketplace"]["facebook"]
    assert cfg["item"]["a"]["max_price"] == "300"


def test_location_keys_hoisted_only_as_a_unit() -> None:
    cfg = _normalize("""
    [marketplace.facebook]
    search_city = "houston"
    radius = 50

    [item.a]
    search_phrases = "a"

    [item.b]
    search_phrases = "b"
    search_city = "dallas"
    radius = 50
    """)
    market = cfg["marketplace"]["facebook"]
    assert "radius" not in market and "search_city" not in market


def test_identical_leftover_notification_sections_are_merged() -> None:
    cfg = normalize(parse("""
    [marketplace.facebook]
    search_city = "houston"

    [user.alice]
    notify_with = "gmail1"
    email = "alice@example.com"

    [user.bob]
    notify_with = "gmail2"
    email = "bob@example.com"

    [notification.gmail1]
    smtp_password = "pw"

    [notification.gmail2]
    smtp_password = "pw"

    [item.a]
    search_phrases = "a"
    """), system_cfg()).config
    assert list(cfg["notification"]) == ["gmail1"]
    assert cfg["user"]["bob"]["notify_with"] == ["gmail1"]


def test_sections_with_different_request_are_not_merged() -> None:
    cfg = normalize(parse("""
    [marketplace.facebook]
    search_city = "houston"

    [user.alice]
    notify_with = "gmail1"
    email = "alice@example.com"

    [notification.gmail1]
    smtp_password = "pw"

    [notification.gmail2]
    request = "spare account"
    smtp_password = "pw"

    [item.a]
    search_phrases = "a"
    """), system_cfg()).config
    assert set(cfg["notification"]) == {"gmail1", "gmail2"}


def test_changes_are_relative_to_the_input() -> None:
    text = USERS + '[marketplace.facebook]\nsearch_city = "houston"\n[item.a]\nsearch_phrases = "a"\n'
    result = normalize(parse(text), system_cfg())
    sections = {c.section for c in result.changes}
    assert "item.a" in sections  # search_city and notify moved into the item
```

In `tests/test_normalize_properties.py`, change the import line to `from ai_marketplace_monitor.normalize import expand, normalize` and append:

```python
@pytest.mark.parametrize("user_cfg", _inputs())
def test_normalize_is_idempotent_pure_and_canonical(user_cfg: Dict[str, Any]) -> None:
    before = copy.deepcopy(user_cfg)
    first = normalize(user_cfg, system_cfg())
    assert user_cfg == before
    assert normalize(first.config, system_cfg()).changes == []
    # an untouched expanded form normalizes back to exactly what is on disk
    expanded = expand(user_cfg, system_cfg()).config
    assert dumps(normalize(expanded, system_cfg()).config) == dumps(first.config)


@pytest.mark.parametrize("user_cfg", _inputs())
def test_normalize_ignores_key_order(user_cfg: Dict[str, Any]) -> None:
    a = normalize(user_cfg, system_cfg()).config
    b = normalize(_shuffled(user_cfg), system_cfg()).config
    assert dumps(a) == dumps(b)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_normalize_compact.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize'`.

- [ ] **Step 3: Implement `compact`**

```python
# src/ai_marketplace_monitor/normalize/compact.py
"""Remove the repetition of the expanded form (internal step of normalize())."""

import copy
from typing import Any, Dict, List, Tuple

from .model import AI_PROMPT_ITEM_ONLY, COMMON_OPTIONS, LOCATION_KEYS
from .pushdown import Notes, bound_marketplace

_ABSENT = object()


def _shared(key: str, group: List[Dict[str, Any]]) -> bool:
    values = [item.get(key, _ABSENT) for item in group]
    return values[0] is not _ABSENT and all(v == values[0] for v in values)


def _hoist(cfg: Dict[str, Any], notes: Notes) -> None:
    markets: Dict[str, Any] = cfg.get("marketplace", {})
    items: Dict[str, Any] = cfg.get("item", {})
    for market_name, market in markets.items():
        group = [it for it in items.values() if bound_marketplace(it, markets) == market_name]
        if len(group) < 2:
            continue
        keys = [
            k
            for k in COMMON_OPTIONS
            if k not in AI_PROMPT_ITEM_ONLY and k not in LOCATION_KEYS and _shared(k, group)
        ]
        location = [k for k in LOCATION_KEYS if any(k in it for it in group)]
        if location and all(_shared(k, group) for k in location):
            keys += location
        for key in keys:
            market[key] = copy.deepcopy(group[0][key])
            notes[(f"marketplace.{market_name}", key)] = f"{key} shared by all items"
            for item in group:
                del item[key]


def _merge_notifications(cfg: Dict[str, Any], notes: Notes) -> None:
    notifs: Dict[str, Any] = cfg.get("notification", {})
    names = list(notifs)
    replace: Dict[str, str] = {}
    for i, keep in enumerate(names):
        if keep in replace:
            continue
        for other in names[i + 1 :]:
            if other not in replace and notifs[other] == notifs[keep]:
                replace[other] = keep
    for other, keep in replace.items():
        del notifs[other]
        notes[(f"notification.{other}", None)] = f"merged into notification.{keep}"
    for user in cfg.get("user", {}).values():
        if isinstance(user.get("notify_with"), list):
            user["notify_with"] = list(dict.fromkeys(replace.get(n, n) for n in user["notify_with"]))


def compact(expanded: Dict[str, Any]) -> Tuple[Dict[str, Any], Notes]:
    """Hoist values shared by all items of a marketplace and merge identical sections."""
    cfg = copy.deepcopy(expanded)
    notes: Notes = {}
    _hoist(cfg, notes)
    _merge_notifications(cfg, notes)
    return cfg, notes
```

- [ ] **Step 4: Implement `normalize`**

Append to `src/ai_marketplace_monitor/normalize/core.py` (add `from .compact import compact` to its imports):

```python
def normalize(user_cfg: Dict[str, Any], system_cfg: Dict[str, Any]) -> NormalizeResult:
    """compact(expand(x)): the only form ever written to disk; never mutates the input."""
    compacted, notes = compact(expand(user_cfg, system_cfg).config)
    result = order_config(compacted)
    check_equivalent(system_cfg, user_cfg, result)
    return NormalizeResult(result, describe_changes(user_cfg, result, notes))
```

Change notes from the expand step are not carried over: `describe_changes` compares the original input with the final output, and keys that were pushed into items and hoisted straight back show no change.

Update `normalize/__init__.py`:

```python
"""Config normalization: expand() for AI editing, normalize() for what is written to disk."""

from .core import expand, normalize
from .effective import check_equivalent, effective_view
from .model import Change, NormalizeError, NormalizeResult

__all__ = [
    "Change",
    "NormalizeError",
    "NormalizeResult",
    "check_equivalent",
    "effective_view",
    "expand",
    "normalize",
]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_normalize_compact.py tests/test_normalize_properties.py -v`
Expected: all PASS.

- [ ] **Step 6: Static checks and commit**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`

```bash
git add src/ai_marketplace_monitor/normalize tests/test_normalize_compact.py tests/test_normalize_properties.py
git commit -m "feat(normalize): add normalize() = compact(expand()) (#362)"
```

---

### Task 11: Changelog and final verification

**Files:**
- Modify: `CHANGELOG.md` (under `## [Unreleased]`)

- [ ] **Step 1: Add changelog entries**

```markdown
### Added
- Option `request` on every config section to record, in your own words, what the section is for; reserved for upcoming AI-assisted configuration ([#362](https://github.com/BoPeng/ai-marketplace-monitor/issues/362))

### Fixed
- `docs/example_config.toml` used an invalid `search_city` value and could not be loaded
```

- [ ] **Step 2: Full verification**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`
Expected: all tests pass; no lint or type errors.

Then, a manual smoke check against the real loader:

```bash
uv run python -c "from ai_marketplace_monitor.config import load_config_dicts; from ai_marketplace_monitor.normalize import expand, normalize; from pathlib import Path; s,u=load_config_dicts([Path('docs/example_config.toml')]); print(expand(u,s).config); print(normalize(u,s).config)"
```

Expected: two dicts printed, no exception; `user1` has `notify_with = ['gmail', 'pushbullet', 'pushover']`.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for config normalization (#362)"
```
