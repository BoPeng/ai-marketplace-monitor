# Design: Config normalization, compaction, and the `request` field

**Date:** 2026-10-04
**Status:** Approved (brainstorm), pending implementation plan

## Summary

Lay the foundation for LLM-assisted configuration (`interpret`, `aimm --chat`, a GUI
chat panel — all out of scope here) with two pieces:

1. A **`request` field** on every config section that is built on `BaseConfig`, holding
   the user's free-text intent for that section.
2. An **internal `normalize()` function** that converts a valid user config into a
   single **canonical form** with the same runtime behavior, so an LLM only ever reads and
   writes one predictable shape. A behavior-equivalence check runs on every call.
3. A **`compact()` function**, the behavioral inverse of `normalize()`, that removes
   repetition from a canonical config so humans can read and review it.

```
file ──normalize──► canonical ──(later: AI edits)──► canonical' ──compact──► human-readable
                         └──────── effective_view ────────┘──► behavior diff for review
```

No files are written by this work. An explicit `aimm --normalize` command (rewrite the
user's file with `tomlkit`, with backups) is a later step built on this function.

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
without `notify_with`). The canonical form removes both problems: one spelling, explicit
lists, and each item self-contained.

## Part 1: the `request` field

- Add `request: str | None = None` to `BaseConfig` (`utils.py`). This covers `ai`,
  `marketplace`, `item`, `user`, `notification`, `region`, and `monitor` sections.
  `[translation.*]` sections are not `BaseConfig` and are excluded (their keys are
  arbitrary page words; a `request` key there would be read as a word to translate).
- `handle_request` rejects any non-string value.
- `request` is **not** `${VAR}`-expanded in `BaseConfig.__post_init__`.
- `request` is **not** copied by `Config.expand_notifications` (add it to the excluded
  keys alongside `type` and `name`), so a notification's request never overwrites a user's.
- `request` is **excluded from `BaseConfig.hash`**, so editing a request does not
  invalidate cached AI ratings (`AI_INQUIRY` is keyed by item and marketplace hashes).
- Nothing at runtime reads `request`.
- Document `request` in the "Additional options" table of `docs/README.md`.

## Part 2: normalization

### Module and API

New module `src/ai_marketplace_monitor/normalize.py` — pure logic, no network, no web UI
imports, no file writes.

```python
@dataclass
class Change:
    section: str          # e.g. "user.alice", "notification.email", "item.bike"
    action: str           # "add" | "move" | "set" | "remove"
    key: str | None
    detail: str           # human-readable explanation

@dataclass
class NormalizeResult:
    config: dict          # canonical user config; system (bundled) sections excluded
    changes: list[Change] # empty -> input was already canonical

class NormalizeError(ValueError): ...

def load_config_dicts(files: list[Path]) -> tuple[dict, dict]:   # (system, merged user)
def normalize(user_cfg: dict, system_cfg: dict) -> NormalizeResult
def compact(user_cfg: dict, system_cfg: dict) -> NormalizeResult   # see "Part 3"
def effective_view(config: Config) -> dict
def check_equivalent(system_cfg: dict, before: dict, after: dict) -> None  # raises NormalizeError
```

Contract:

- **Input must be a valid config** (loads with `Config`); otherwise `NormalizeError` with
  the loader's message. Sections that have only a `request` ("pending") are a later step.
- **Input is not mutated.** `merge_dicts` mutates nested dicts, so `normalize` deep-copies.
- **Idempotent:** `normalize(normalize(x).config).changes == []`.
- **Raw values are preserved verbatim:** `"1h"` stays `"1h"`, `${ENV}` stays a
  placeholder, literal secrets stay literal. Normalize operates on the parsed-but-
  unprocessed dict, never on loaded `Config` objects (which have converted durations,
  expanded secrets, and expanded regions).
- **Bundled sections** (`config.toml` regions and translations) are consulted but never
  copied into the output.
- **Equivalence is always checked**: `normalize` calls `check_equivalent` before returning
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

### Canonical form: rules

Output section order: `monitor`, `ai`, `marketplace`, `user`, `notification`, `region`,
`item`, `translation`. Within a section, original key order is kept and added keys are
appended. `request` always stays in the section where it was written.

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

For each user, iterating `notify_with` in order (or all notification sections when unset):

1. **Winner per field.** Sources, in precedence order: the user's raw section, then each
   enabled notification section in order (including the dataclass defaults of its
   inferred type). If the winner is a raw value, carry that raw value; if the winner is a
   **default**, omit the field (the same default re-applies after normalization) and
   record a `remove` change for any inline value it shadowed.
2. **Active channels.** A channel type is active when all its `required_fields` are present
   in the merged result.
3. **Recipient fields** go into `[user.x]`, even if they came from a notification section
   (e.g. a shared group `telegram_chat_id`).
4. **Channel fields** go into `[notification.*]` sections. Users whose channel field-sets
   for a type are identical share one section. Naming: reuse an existing section whose
   channel content matches; else the type name (`email`, `telegram`, `pushbullet`,
   `pushover`, `ntfy`); else `<type>_<user>`.
5. **`notify_with`** is set to exactly the user's active-channel sections; `[]` if none
   (`[]` means none, unset means all).
6. **Leftovers:** notification sections that end up unreferenced, and disabled ones, are
   kept unchanged. Normalize never deletes user-authored sections.

#### Marketplaces and items: push down

Every item becomes self-contained:

- For every common option (`MarketItemCommonConfig` / `FacebookMarketItemCommonConfig`
  fields, including `notify` and `ai`) set on a marketplace, copy the marketplace's raw
  value into each item that would fall back to it per `resolve_option`, then remove it
  from the marketplace. Under the *truthy* rule an item's falsy value (e.g.
  `min_price = 0`, `notify = []`) falls back, so it is replaced; under the *not-None*
  rule an item's empty value (e.g. `seller_locations = []`, `ai = []`) is kept.
- **Explicit defaults:** after push-down, an item with no `notify` gets the list of all
  users; an item with no `ai` gets the list of all `[ai.*]` sections. If no AI sections
  exist, `ai` is omitted. `ai = []` is kept (it means "no AI").
- **Marketplace-only keys stay:** `username`, `password`, `login_wait_time`, `language`,
  `market_type`, `enabled`, `request`. A marketplace's `request` remains the place for
  shared intent; a later `interpret` propagates it into items.
- **Multiple marketplaces guard:** if an item without a `marketplace` key would be searched
  in more than one enabled marketplace and those marketplaces would resolve any option
  differently, push-down is ambiguous: raise `NormalizeError`. (Only Facebook exists
  today, so this is a defensive check.)
- **Accepted behavior change — AI prompt prices.** `get_prompt` reads `min_price` /
  `max_price` from the item only. Pushing a marketplace-level price into items makes it
  appear in the AI prompt, which it did not before. This is treated as a fix, not a
  regression: `check_equivalent` allows exactly this difference, and `normalize` records
  it as a `set` change with a detail saying so.

A consequence of explicit `notify`: users added **later** are not notified automatically;
`interpret` / chat add them where intended.

#### Everything else

`ai`, `region`, `monitor`, and `translation` sections pass through unchanged. Secrets are
not touched (redaction for the LLM view is a later step).

### Behavior-equivalence check

**`effective_view(config)`** returns a JSON-able dict, for every (marketplace, item) pair
that will actually be searched (both enabled, item's `marketplace` matching or unset):

- every common option resolved through `resolve_option`, per use site (so the AI-prompt
  price is a separate entry from the search price);
- recipients: the resolved user list, and per user the active channel types and the
  user's post-merge notification fields;
- the resolved AI backend list.

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

## Part 3: compaction

Canonical form is easy for an LLM but repetitive for people (every item repeats
`search_city`, `radius`, `notify`, ...). `compact()` produces the human-oriented form used
for configs created from scratch (e.g. by the future chat) and for a future
`aimm --normalize --compact`. Edits to an *existing* file will instead use a
layout-preserving `apply_changes` (out of scope, see below), because compaction alone
can turn a one-value edit into a many-section diff (e.g. one item's `radius` changes from
the shared value, so the hoisted `radius` must be pushed back into every item).

### Contract

- Accepts any valid user config; it calls `normalize()` first, then compacts. `changes`
  are reported relative to the input.
- Same guarantees as `normalize`: input not mutated, raw values verbatim, bundled sections
  not copied, deterministic output order, and `check_equivalent` always runs (with the
  same single allowed AI-prompt-price difference when the input was not canonical).
- Idempotent: `compact(compact(x).config).changes == []`.
- Round-trip: `compact(normalize(compact(x).config).config).config == compact(x).config`.

### Rules

1. **Hoist shared item values to the marketplace.** For each marketplace, take the group
   of items bound to it (including disabled items, so re-enabling one later does not
   change its behavior). If the group has **at least two** items and **every** item sets
   a common option to the **same raw value**, set that value on the marketplace and remove
   it from the items. Values that differ stay on the items; there are no partial
   ("most common value") hoists.
   - Because an item loses only a value equal to the hoisted one, fallback under both the
     *truthy* and *not-None* rules yields the same value.
   - **Never hoist an option that has an item-only use site** in `resolve_option`
     (currently `min_price` / `max_price`, read only from the item by the AI prompt).
   - With more than one enabled marketplace, only items with an explicit `marketplace`
     key are grouped; items without it are left unchanged.
2. **Lists stay explicit.** `notify` and `ai` may be hoisted like any other option, but
   compaction never deletes them in favor of the implicit "all users" / "all AI" default.
3. **Merge identical notification sections.** Two `[notification.*]` sections of the same
   type with identical raw content (and no `request`, or identical `request`) are merged
   into the one that comes first in output order; every user's `notify_with` is updated
   and de-duplicated preserving order.
4. Everything else (user recipient fields, `ai`, `region`, `monitor`, `translation`,
   marketplace-only keys, `request` placement) is unchanged.

## Testing

New `tests/test_normalize.py`, plus additions to existing test files.

- **Characterization first (TDD):** for every common option, pin current fallback
  behavior through the real code paths (facebook search-URL builder following
  `tests/test_facebook_sort_by.py`, listing filters, monitor rating/notify/AI/schedule
  resolution, `ai.py` prompt selection), including falsy-vs-None edge cases. Switch call
  sites to `resolve_option` only with these green before and after.
- **`request`:** accepted on each `BaseConfig` section type; non-string rejected; not
  `${}`-expanded; not merged into users; excluded from `BaseConfig.hash`.
- **`Config.from_dicts`:** equals file-based loading on the bundled examples.
- **Rules, one case each:** inline single user; shared SMTP with per-user `email`; group
  `telegram_chat_id` in a notification section; `notify_with` unset vs `[]`; default
  overriding inline `max_retries`; same-type override quirk; disabled and unused
  notification sections kept; marketplace `notify`/`ai` missing or `[]`; no AI sections;
  push-down past truthy-rule falsy item values and not-None-rule empty item values;
  marketplace-only keys stay; AI-prompt price change recorded; region references and
  `${ENV}` / `"1h"` spelling preserved; bundled regions not copied; translation passthrough;
  multiple-marketplace guard raises.
- **Properties on every case and on `docs/example_config.toml`, `docs/minimal_config.toml`,
  and the TOML examples in `docs/README.md`:** equivalence holds; idempotent; input not
  mutated.
- **Compaction, one case each:** hoist when all items agree; no hoist when one differs;
  no hoist with a single item; disabled item blocks a hoist when it differs;
  `min_price` / `max_price` never hoisted; `notify` / `ai` hoisted as explicit lists;
  identical notification sections merged and `notify_with` updated; sections with
  different `request` not merged; multi-marketplace items without `marketplace` key left
  alone.
- **Compaction properties on every case and the bundled examples:** equivalence holds;
  idempotent; round-trip with `normalize` as stated above.
- **Negative:** tampering with normalized output makes `check_equivalent` raise with the
  right path and masked secrets.

## Out of scope (later steps)

- `aimm --normalize [--compact]`, `tomlkit` write-back to the originating file, and
  backups.
- `apply_changes(original_raw, canonical_before, canonical_after)`: apply only the
  semantic delta of an AI edit onto the user's existing file layout (minimal diff),
  guarded by `check_equivalent`. Belongs with write-back.
- LLM view with secret redaction.
- `interpret`, pending (request-only) sections, request staleness hash.
- `aimm --chat` and the GUI chat panel.
- Fixing the two `expand_notifications` quirks (normalization rules to be updated with
  that fix).
- Hashing effective values for the AI cache.
