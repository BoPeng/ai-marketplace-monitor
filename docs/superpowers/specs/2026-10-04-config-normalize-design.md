# Design: Config expansion, normalization, and the `request` field

**Date:** 2026-10-04
**Status:** Approved; implemented in #366

## Summary

Lay the foundation for LLM-assisted configuration (`interpret`, `aimm --chat`, a GUI
chat panel — all out of scope here) with two pieces:

1. A **`request` field** on every config section that is built on `BaseConfig`, holding
   the user's free-text intent for that section.
2. **`expand()`**: converts a valid user config into a single explicit, repetitive
   **expanded form** with the same runtime behavior, so an LLM only ever reads and edits
   one predictable shape. It exists only in memory and is **never written to disk**.
3. **`normalize()` = compact(expand(x))**: removes the repetition again (Part 3). This is
   the **only form ever written to disk**. Because it is computed from the expanded form,
   defaults and key placement normalize to one concise spelling. Section order within a
   type is preserved where the runtime treats order as meaningful (for example first
   marketplace binding, item processing order, AI order, and notification merge order).

A behavior-equivalence check runs on every `expand` and `normalize` call.

```
disk ──expand──► expanded ──(later: AI edits)──► expanded' ──normalize──► disk
   (compact)          └────────── effective_view ──────────┘──► behavior diff for review
```

No files are written by this work. Writing `normalize()` output back to the user's file
(with backups) is a later step. Consequence of "disk is always normalized": the first
save rewrites a hand-written file into the normalized layout, and a one-value edit can
move a key between a marketplace and its items (e.g. one item's `radius` diverging from
the shared value pushes `radius` back into every item). Review therefore relies on the
behavior diff, not the TOML diff.

## Motivation

The current config format allows several equivalent spellings of the same setup and has
implicit "everyone" defaults:

- Notification settings may be inline in `[user.x]`, in `[notification.x]`, or split and
  merged across both.
- Common options may be set on the marketplace, the item, or both.
- An omitted `notify` means *all users*, an omitted `notify_with` means *all
  notification sections*, an omitted `ai` means *all AI backends*.

An LLM editing such a file produces inconsistent output and, worse, edits whose effect
reaches other sections (adding `[notification.telegram]` silently notifies every user
without `notify_with`). The expanded form removes both problems: one spelling, explicit
lists, and each item self-contained.

## Part 1: the `request` field

- Add `request: str | None = None` to `BaseConfig` (`utils.py`). This covers `ai`,
  `marketplace`, `item`, `user`, `notification`, `region`, and `monitor` sections, and
  `translation` once it becomes a `BaseConfig` (below).
- **Translation sections become `BaseConfig`** (implemented in #364, with `TRANSLATION_FIELDS = ("enabled", "locale")`; this work adds `"request"`). Today `[translation.*]` is loaded into a
  plain `Translator` (`locale` plus every other key as a word mapping), so it has neither
  `request` nor `enabled`. Translations are a natural LLM task (a later `interpret` can
  generate `[translation.de]` from `request = "I search Facebook Marketplace in Germany"`),
  so add:

  ```python
  TRANSLATION_FIELDS = ("request", "enabled", "locale")

  @dataclass
  class TranslationConfig(BaseConfig):
      locale: str | None = None
      dictionary: Dict[str, str] = field(default_factory=dict)
  ```

  The loader sends `TRANSLATION_FIELDS` keys to the fields and every other key to
  `dictionary`. Translatable keys are a fixed set of Facebook UI strings, none of which is
  `request`, `enabled`, or `locale`, so there is no collision. `handle_locale` keeps the
  existing "must contain a locale" error; `handle_dictionary` requires string values.
  `Translator` stays the runtime lookup object, built from an enabled `TranslationConfig`
  (and gains a read-only `dictionary` property); no lookup site changes.
  `enabled = false` drops the section from `Config.translator`, and the marketplace
  `language` check uses `Config.translator` (enabled translations), so a marketplace
  whose language is only covered by a disabled translation fails with the existing
  "Translation for language ... is not supported" error.
  Risk for the later `interpret` step (not this work): translated strings must equal
  Facebook's exact UI text, and a wrong one silently falls back to English (the bundled
  Spanish translation had two headings swapped, fixed separately in #364), so generated
  translations need user confirmation.
- `handle_request` rejects any non-string value.
- `request` is **not** `${VAR}`-expanded in `BaseConfig.__post_init__`.
- `request` is **not** copied by `Config.expand_notifications` (add it to the excluded
  keys alongside `type` and `name`), so a notification's request never overwrites a user's.
- `request` is **excluded from `BaseConfig.hash`**, so editing a request does not
  invalidate cached AI ratings (`AI_INQUIRY` is keyed by item and marketplace hashes).
- Nothing at runtime reads `request`.
- Document `request` in the "Additional options" table of `docs/README.md`.

## Part 2: expansion

### Module and API

New package `src/ai_marketplace_monitor/normalize/` (imported as
`ai_marketplace_monitor.normalize`, one focused file per concern) — pure logic, no
network, no web UI imports, no file writes. Secret-key detection (`is_sensitive_key`)
moves from `webui/secrets_redact.py` to `utils.py` so both can use it.

```python
@dataclass
class Change:
    section: str          # e.g. "user.alice", "notification.email", "item.bike"
    action: str           # "add" | "move" | "set" | "remove"
    key: str | None
    detail: str           # human-readable explanation

@dataclass
class NormalizeResult:
    config: dict          # expanded or normalized user config; system (bundled) sections excluded
    changes: list[Change] # empty -> input was already in that form

class NormalizeError(ValueError): ...

def load_config_dicts(files: list[Path]) -> tuple[dict, dict]:   # (system, merged user)
def expand(user_cfg: dict, system_cfg: dict) -> NormalizeResult     # in memory only
def normalize(user_cfg: dict, system_cfg: dict) -> NormalizeResult  # compact(expand(x)); see Part 3
def effective_view(config: Config) -> dict
def check_equivalent(system_cfg: dict, before: dict, after: dict) -> None  # raises NormalizeError
```

Contract:

- **Input must be a valid config** (loads with `Config`); otherwise `NormalizeError` with
  the loader's message. Sections that have only a `request` ("pending") are a later step.
- **Input is not mutated.** `merge_dicts` mutates nested dicts, so `expand` deep-copies.
- **Idempotent:** `expand(expand(x).config).changes == []`.
- **Raw values are preserved verbatim:** `"1h"` stays `"1h"`, `${ENV}` stays a
  placeholder, literal secrets stay literal. Expansion operates on the parsed-but-
  unprocessed dict, never on loaded `Config` objects (which have converted durations,
  expanded secrets, and expanded regions).
- **Bundled sections** (`config.toml` regions and translations) are consulted but never
  copied into the output.
- **Equivalence is always checked**: `expand` calls `check_equivalent` before returning
  and raises `NormalizeError` on any difference.

### Supporting refactors (behavior-preserving)

1. **`load_config_dicts` / `Config.from_dicts`.** Extract file parsing + merging from
   `Config.__init__` into `load_config_dicts`, and let `Config` be built from
   already-parsed dicts (`Config.from_dicts(system, user, logger)`), which `__init__` uses.
2. **`resolve_option(key, item, marketplace)`** in `marketplace.py`: one helper plus a
   table recording, per common option, how an item value falls back to the marketplace
   value. Today this is inconsistent across call sites:
   - *truthy* (`item.x or marketplace.x`): e.g. `notify`, `min_price`, `max_price`,
     `search_city`, `radius`, `currency`, `category`, `sort_by`, `condition`,
     `start_at`, `search_interval`, `max_search_interval`, `rating`, `date_listed`,
     `delivery_method`, `availability`;
   - *not-None* (`item.x if item.x is not None else marketplace.x`): e.g. `ai`,
     `seller_locations`, `exclude_sellers`, `prompt`, `extra_prompt`, `rating_prompt`;
   - *item-only* (marketplace value ignored): `min_price` / `max_price` **in the AI
     prompt** (`ai.py` `get_prompt`).

   The table is keyed by (option, use site) where a use site differs, and is established
   by characterization tests against the current code before the call sites in
   `facebook.py`, `monitor.py`, and `ai.py` are switched to the helper. The plan must
   enumerate every call site; the list above is indicative.

3. **Field facts live on the fields** (dataclass metadata), not in separate tables:
   - common options are declared with `option(rule, item_only_in=..., location=...)`
     (`marketplace.py`), and `option_fallbacks(cls)`, `site_fallbacks(cls)`,
     `location_keys(cls)` read them; `resolve_option` takes the rules from the item's
     own class;
   - notification fields are declared with `notification_field(role)` where role is
     `recipient`, `channel` or `common` (`notification.py`), read by
     `fields_with_role(cls, role)`.

   A new option or notification field therefore declares its normalization behavior
   where it is defined, and tests fail if one is declared without a rule/role. Secret
   detection stays name-based (`is_sensitive_key`), because the web UI redacts raw TOML
   keys that may not belong to any config class.

### Expanded form: rules

`request` always stays in the section where it was written.

#### Ordering

The parsed dict (`tomllib`) already groups sections by type, so an interleaved file
layout (e.g. `[notification.telegram]` placed next to `[user.alice]`) cannot survive
expansion or compaction, and is not preserved on disk either (disk always holds
`normalize()` output). Both `expand` and `normalize` emit:

1. **Fixed type order:** `monitor`, `ai`, `marketplace`, `user`, `notification`,
   `region`, `item`, `translation`.
2. **Stable order within a type — never sorted.** Within-type order is
   behavior-relevant: an item without a `marketplace` key binds to the *first*
   marketplace (`Config.get_item_config`), items are scheduled and searched in config
   order, and notification sections are merged in order when `notify_with` is unset
   (expansion makes it explicit, but the input's order decides which value wins). The
   order is the merged-input order. New sections (e.g. a `[notification.email]` split out
   of inline user settings) are appended after existing sections of their type; a merged
   notification section (compaction) keeps the position of the first of the two.
3. **Fixed key order within a section:** `request`, then `enabled`, then the remaining
   fields in the declaration order of the section's config dataclass (for marketplaces
   and items, the Facebook dataclasses, base-class fields first). Any key not declared on
   the dataclass (none should survive validation) goes last in input order. For
   `[translation.*]` that means `request`, `enabled`, `locale`, then the translated words
   in input order (their order carries no meaning, and the words are user data). A fixed key
   order makes the output a function of content only, so a section an LLM
   returns with keys in arbitrary order normalizes back to an identically ordered dict (compare with
   `json.dumps` without `sort_keys`; plain `==` ignores order) and the before/after diff shows only real edits.

#### Users and notifications

Normalization must reproduce **actual** runtime behavior of `expand_notifications`,
including two quirks (separate bugs, not fixed here):

- **Defaults override inline values.** The merge copies every non-`None` field of the
  notification object, including dataclass defaults; e.g. a user's inline
  `max_retries = 3` is replaced by a notification section's default `5`.
- **Same-type deduplication is ineffective.** `notification_types` is reset inside the
  loop, so a later section of the same type overrides an earlier one.

Field classification:

| Kind | Fields | Lives in |
|---|---|---|
| Recipient (*who*) | `email`, `telegram_chat_id`, `pushover_user_key`, `ntfy_topic` | `[user.x]` |
| Channel (*how*) | `smtp_server`, `smtp_port`, `smtp_username`, `smtp_password`, `smtp_from`, `telegram_token`, `pushover_api_token`, `pushbullet_token`, `pushbullet_proxy_type`, `pushbullet_proxy_server`, `ntfy_server`, `message_format`, `with_description`, `max_retries`, `retry_delay`, `rate_limit_enabled`, `instance_rate_limit`, `global_rate_limit` | `[notification.x]` |

User-only fields (`notify_with`, `remind`, `enabled`, `request`) stay in the user.

"Type" of a field is decided by **which class declares it**, not by the class
`NotificationConfig.get_config` infers for a section: inference walks subclasses and
usually lands on `UserConfig` (e.g. a section with only `telegram_token` loads as a
`UserConfig`), so a section's defaults are those of whatever class it actually loads as.
Common fields are those declared on `NotificationConfig` / `PushNotificationConfig`;
type-specific fields are the rest of `EmailNotificationConfig`,
`PushbulletNotificationConfig`, `PushoverNotificationConfig`, `NtfyNotificationConfig`,
`TelegramNotificationConfig` (minus the common ones they redeclare). Private fields
(leading `_`) are never written.

For each user, with sources = the user's raw section, then each enabled notification
section in `notify_with` order (all notification sections when unset):

1. **Effective values `E`** are the user's fields after the real merge (the loaded
   `Config.user[u]`). **Raw provenance `P[f]`** is the raw value from the source that wins
   field `f` under the same precedence (later section wins whenever its loaded instance
   has a non-`None` value, raw or default); `P[f]` is `None` when the winner is a default.
   Placement decisions use `P` (so `${VAR}` placeholders whose variable is unset still
   count as present); written values are `P[f]`, or `E[f]` where a default must be made
   explicit.
2. **Recipient fields** with `P[f]` present go into `[user.x]`, even if they came from a
   notification section (e.g. a shared group `telegram_chat_id`).
3. **One channel section per type** that has at least one type-specific channel field
   with `P[f]` present, containing those fields.
4. **Common fields:** in each channel section, write a common field only when the value
   the section would load to differs from `E[f]`; "default" means the value the section
   actually loads with (a real load, not the dataclass default, since `handle_*` hooks
   can set values, e.g. `message_format` becomes `"plain_text"`). Explicit values equal
   to that loaded value are dropped (no runtime effect; disk always holds normalized
   output). Raw values that loading always overrides (e.g. an inline user
   `message_format = "markdown"`, which a `UserConfig` load forces to `"plain_text"`) count
   as not set. If a section's loaded class **cannot hold** `E[f]` (its hook forces another
   value), `f` is not written there and the section is a **forcing** section (see step 6).
   Every non-forcing section then applies exactly `E[f]`. A shadowed inline value (e.g.
   `max_retries = 3` overridden by a section default) is dropped and reported as a
   removed key in the change list. If the user ends up with **no** channel sections,
   common fields with `P[f]` present stay in the user.
5. **Sharing and naming:** users whose sections for a type have identical content share
   one section. Name, in order of preference: the existing section that supplied the
   winning type-specific fields (if not already claimed by a different content); else the
   type name (`email`, `telegram`, `pushbullet`, `pushover`, `ntfy`) if free; else
   `<type>_<first user>`.
6. **`notify_with`** is set to exactly the user's channel sections: forcing sections first,
   then the rest, each group in the fixed type order email, pushbullet, pushover, ntfy,
   telegram (so a section that forces e.g. `message_format = "plain_text"` is merged before
   the section that carries the user's real value); `[]` if none (`[]` means none, unset
   means all).
7. **Leftovers:** existing notification sections not claimed in step 5, and disabled ones,
   are kept unchanged. Normalize never deletes user-authored sections.

#### Marketplaces and items: push down

Every item becomes self-contained. Each item is bound to exactly one marketplace:
its `marketplace` key, or else the **first** marketplace in the config
(`Config.get_item_config` always sets `item.marketplace`, and `validate_items` / the
monitor only pair an item with that marketplace).

- For every common option (`MarketItemCommonConfig` / `FacebookMarketItemCommonConfig`
  fields, including `notify` and `ai`) set on the bound marketplace, copy the
  marketplace's raw value into each item that would fall back to it per
  `resolve_option`, then remove it from the marketplace. Under the *truthy* rule an
  item's falsy value (e.g. `notify = []`, `search_city = []`) falls back, so it is
  replaced; under the *not-None* rule an item's empty value (e.g.
  `seller_locations = []`, `ai = []`) is kept. (Prices are normalized to strings by the
  loader, so `min_price = 0` is `"0"` and does not fall back.)
- **Location keys:** if the item has its own `search_region`, its `search_city`,
  `city_name`, `radius`, `currency` come from region expansion, so none of these five
  keys is copied to it. Otherwise each is copied independently by the rule above. If the
  copied result fails to load (e.g. a marketplace `radius` list whose length does not
  match the item's own `search_city`), `NormalizeError` names the item and key.
  Likewise, an item with its own `search_city` that would inherit `radius` / `currency`
  from a marketplace's `search_region` raises `NormalizeError` naming the item (set them
  on the item or give it its own `search_region`).
- **Explicit defaults:** after push-down, an item with no `notify` gets the list of all
  users; an item with no `ai` gets the list of all `[ai.*]` sections. If no AI sections
  exist, `ai` is omitted. An item with no `marketplace` key gets the marketplace it is
  bound to (the first marketplace). `ai = []` is kept (it means "no AI").
- **Marketplace-only keys stay:** `username`, `password`, `login_wait_time`, `language`,
  `market_type`, `enabled`, `request`. A marketplace's `request` remains the place for
  shared intent; a later `interpret` propagates it into items.
- **Accepted behavior change — AI prompt prices.** `get_prompt` reads `min_price` /
  `max_price` from the item only. Pushing a marketplace-level price into items makes it
  appear in the AI prompt, which it did not before. This is treated as a fix, not a
  regression: `check_equivalent` allows exactly this difference, and `expand` records
  it as a `set` change with a detail saying so.

A consequence of explicit `notify`: users added **later** are not notified automatically;
`interpret` / chat add them where intended. This holds in normalized (on-disk) files too,
so a future CLI should warn when it adds explicit lists.

#### Everything else

`ai`, `region`, `monitor`, and `translation` sections pass through unchanged. Secrets are
not touched (redaction for the LLM view is a later step).

### Behavior-equivalence check

**`effective_view(config)`** returns a JSON-able dict with, for every item (keyed by
item name, under its bound marketplace `item.marketplace`):

- `enabled` of the item and its marketplace;
- every common option resolved through `resolve_option`, per use site (so the AI-prompt
  price is a separate entry from the search price); `search_region` itself is not
  compared, its expansion into the four location keys is;
- item-only fields (`search_phrases`, `keywords`, `antikeywords`, `description`);
- recipients: the resolved user list (`notify`, falling back to all users), and per user
  the post-merge `UserConfig` fields except `name`, `request`, `notify_with`, and private
  fields;
- the resolved AI backend list (`None` → all `[ai.*]` names);

plus, unchanged-by-design parts: marketplace-only fields per marketplace, `ai` and
`monitor` sections (all fields except `request`), and each enabled translation's `locale`
and `dictionary`.

**`check_equivalent(system, before, after)`** builds both configs with
`Config.from_dicts`, computes both effective views, and raises `NormalizeError` listing
each differing path (e.g. `item.bike.notify: [alice, bob] -> [alice]`), with secret values
masked. The only allowed difference is the AI-prompt price entry described above.

`effective_view` is also the seed of the later effective-config view for the LLM and the
behavior-diff preview; those consumers must mask secrets.

### AI cache effect

`AI_INQUIRY` cache keys include the full item and marketplace hashes. Normalization
changes section contents, so the first run after a normalized config is applied
re-evaluates cached listings once (extra AI calls). Notifications are not duplicated —
`USER_NOTIFIED` is keyed by listing. Hashing effective values instead is out of scope.

## Part 3: compaction and `normalize()`

Canonical form is easy for an LLM but repetitive for people (every item repeats
`search_city`, `radius`, `notify`, ...). Compaction turns the expanded form into the
normalized form that is written to disk. `compact()` is an internal step; the public
entry point is `normalize()`.

### Contract

- `normalize()` accepts any valid user config; it calls `expand()`, then compacts.
  `changes` are reported relative to the input.
- Same guarantees as `expand`: input not mutated, raw values verbatim, bundled sections
  not copied, deterministic output order, and `check_equivalent` always runs against the
  original input (with the same single allowed AI-prompt-price difference).
- Idempotent: `normalize(normalize(x).config).changes == []`.
- Canonical: `normalize(expand(x).config).config == normalize(x).config` (so an AI edit of
  the expanded form normalizes back to exactly what was on disk when nothing changed).

### Rules

1. **Hoist shared item values to the marketplace.** For each marketplace, take the group
   of items bound to it (including disabled items, so re-enabling one later does not
   change its behavior). If the group has **at least two** items and **every** item sets
   a common option to the **same raw value**, set that value on the marketplace and remove
   it from the items. Values that differ stay on the items; there are no partial
   ("most common value") hoists.
   - Because an item loses only a value equal to the hoisted one, fallback yields the same
     value under the *not-None* rule, and under the *truthy* rule **only for truthy
     values**: a shared falsy value (e.g. `rating = []`) of a truthy-rule option is never
     hoisted, since `[] or None` (item keeps it) and `None or []` (hoisted) differ.
   - **Never hoist an option that has an item-only use site** in `resolve_option`
     (currently `min_price` / `max_price`, read only from the item by the AI prompt).
   - Items are grouped by bound marketplace (explicit key, else the first marketplace).
   - **Location keys are hoisted as a unit:** `search_region`, `search_city`,
     `city_name`, `radius`, `currency` are hoisted only if every one of them present on
     any item of the group is hoistable; otherwise none is (a marketplace with `radius`
     but no `search_city` would not load).
2. **Drop values that only restate defaults.** After hoisting, compaction removes:
   `enabled = true`; `[ai.*].max_retries = 10`; `[marketplace.*].market_type =
   "facebook"`; an item `marketplace` equal to the first marketplace; marketplace
   `notify` equal to all users; marketplace `ai` equal to all AI backends; and item
   `notify` / `ai` equal to the value the item would inherit. This keeps the disk form
   concise and canonical while preserving explicit non-default selections, including
   `ai = []` under the not-None fallback rule.
3. **Drop default `notify_with` only when order is also default.** A user's `notify_with`
   is removed when it exactly equals all enabled notification sections in notification
   section order. Other lists stay explicit because notification merge order can affect
   runtime behavior.
4. **Merge identical notification sections.** Two `[notification.*]` sections of the same
   type with identical raw content (and no `request`, or identical `request`) are merged
   into the one that comes first in output order; every user's `notify_with` is updated
   and de-duplicated preserving order.
5. Everything else (user recipient fields, `ai`, `region`, `monitor`, `translation`,
   marketplace-only keys, `request` placement) is unchanged.

## Testing

New `tests/test_normalize_*.py` files, plus additions to existing test files.

- **Characterization first (TDD):** for every common option, pin current fallback
  behavior through the real code paths (facebook search-URL builder following
  `tests/test_facebook_sort_by.py`, listing filters, monitor rating/notify/AI/schedule
  resolution, `ai.py` prompt selection), including falsy-vs-None edge cases. Switch call
  sites to `resolve_option` only with these green before and after.
- **`request`:** accepted on each `BaseConfig` section type; non-string rejected; not
  `${}`-expanded; not merged into users; excluded from `BaseConfig.hash`.
- **Translation sections:** `request` and `enabled` are not treated as words;
  `enabled = false` removes the translation and a marketplace relying on it fails the
  language check; a missing `locale` keeps its error; non-string values rejected;
  bundled translations look up exactly as before.
- **`Config.from_dicts`:** equals file-based loading on the bundled examples.
- **Rules, one case each:** inline single user; shared SMTP with per-user `email`; group
  `telegram_chat_id` in a notification section; `notify_with` unset vs `[]`; default
  overriding inline `max_retries`; same-type override quirk; disabled and unused
  notification sections kept; marketplace `notify`/`ai` missing or `[]`; no AI sections;
  push-down past truthy-rule falsy item values and not-None-rule empty item values;
  marketplace-only keys stay; AI-prompt price change recorded; region references and
  `${ENV}` / `"1h"` spelling preserved (including an unset `${VAR}` channel field);
  bundled regions not copied; translation passthrough; item binds to the first
  marketplace; item with own `search_region` gets no location keys; incompatible
  location push-down raises `NormalizeError` naming the item.
- **Properties on every case and on `docs/example_config.toml` (whose `search_city =
  'another city'` is invalid today and is fixed to `'anothercity'`) and
  `docs/minimal_config.toml`:** equivalence holds; idempotent; input not
  mutated.
- **Ordering:** type order is fixed regardless of input order; marketplace and item order
  is preserved (an item without `marketplace` stays bound to the same marketplace);
  split-out notification sections are appended after existing ones; a config whose
  sections have their keys shuffled expands (and normalizes) to output identical to the unshuffled one, compared
  order-sensitively via `json.dumps`.
- **Compaction, one case each:** hoist when all items agree; no hoist when one differs;
  no hoist with a single item; disabled item blocks a hoist when it differs;
  `min_price` / `max_price` never hoisted; default `notify` / `ai` / `notify_with`
  lists removed; non-default lists kept; identical notification sections merged and
  `notify_with` updated; sections with different `request` not merged; location keys
  hoisted only as a unit.
- **`normalize` properties on every case and the bundled examples:** equivalence holds;
  idempotent; canonical as stated above.
- **Negative:** tampering with expanded output makes `check_equivalent` raise with the
  right path and masked secrets.

## Out of scope (later steps)

- `aimm --normalize`, writing `normalize()` output back to the originating file, and
  backups. (A layout-preserving `apply_changes` is dropped: disk always holds normalized
  output.)
- LLM view with secret redaction.
- `interpret`, pending (request-only) sections, request staleness hash.
- `aimm --chat` and the GUI chat panel.
- Fixing the two `expand_notifications` quirks (normalization rules to be updated with
  that fix).
- Hashing effective values for the AI cache.
