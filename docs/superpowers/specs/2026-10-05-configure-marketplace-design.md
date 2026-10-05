# Design: AI-assisted `aimm-configure marketplace`

**Date:** 2026-10-05
**Status:** Draft, for review

## Summary

`aimm-configure marketplace` (and `marketplace.NAME`) lets a user describe, in a few sentences of
their own words, how they want to search Facebook Marketplace. An LLM turns the description into a
`[marketplace.NAME]` section, shows it, and revises it from free-text adjustments until the user
accepts. The result is applied to the **expanded** config and written to disk in **normalized**
(compacted) form.

It is the first AI-driven section builder, and it brings back the generic structure designed
earlier (`SectionBuilder`, field guides, playbooks), which was removed before #368 merged because
nothing concrete used it. The item builder will reuse all of it.

Decisions made while designing:

| Topic | Decision |
|---|---|
| Structure | Generic `SectionBuilder` framework; marketplace is its first AI-driven builder |
| Field facts | Each field's group (own / shared with items / location) comes from dataclass metadata; field guides add only human guidance |
| LLM protocol | Structured JSON turns, validated by aimm; provider-agnostic, no tool calling |
| Conversation | One generic description prompt; the LLM fills as many fields as it can; aimm shows the section and asks "anything to adjust?"; no per-field questions |
| Shared fields with existing items | Change only items that use the marketplace-wide value; items with their own value keep it |
| Write path | One user config file: rewrite it in normalized form after a backup (comments are lost). Several files: write only the changed sections into the files that define them |

## Goals and non-goals

Goals:

- `aimm-configure marketplace` / `marketplace.NAME` creates or updates a marketplace section from a
  free-text description, then exits after the user confirms and the file is written.
- A usable AI is required; without one, the user is offered AI setup first.
- A playbook and field guides tell the LLM which fields exist, which belong to the marketplace
  only, which are shared defaults for items, how to determine each, and the accepted formats.
- The section keeps a `request` that summarizes the user's requirements so far.
- The framework (`SectionBuilder`, playbooks, `run_turn`, `commit_config`) is generic.

Non-goals (later work): the item builder, builders for `user` / `notification` / `region`, a GUI
front end (the `SetupUI` protocol and `JsonSetupUI` already allow one), and `aimm --chat`.

## 1. Architecture and components

New and changed modules (all under `src/ai_marketplace_monitor/` unless noted):

| Module | Role |
|---|---|
| `configure/sections.py` | `FieldGroup`, `FieldGuide`, `SectionDraft`, `TurnResult`, `SectionBuilder` base class with the generic loop, `BUILDERS` registry |
| `configure/playbooks.py` | load bundled playbooks and user house rules; build LLM instructions |
| `configure/playbooks/AGENT.md`, `configure/playbooks/marketplace.md` | bundled playbooks (package data) |
| `configure/llm.py` | `run_turn()`: one structured JSON turn with validation retries |
| `configure/marketplace.py` | `MarketplaceBuilder`: field guides, `view()`, `apply()` |
| `configure/writer.py` | add `commit_config()` (normalize, preview, back up, write, verify) |
| `configure/flow.py`, `configure/cli.py` | `marketplace` / `marketplace.NAME` addresses; front-door entry |
| `config_toml.py` (new, moved from `cli.py`) | `dump_config_toml(cfg)`, shared by `aimm --normalize-config` and the writer |
| `ai.py` | `AIBackend.chat(messages, *, json_mode=False) -> str` for OpenAI-compatible providers and Anthropic |
| `normalize/pushdown.py` | keep shared options on a marketplace that has no items (section 4A) |

### Types

```python
class FieldGroup(Enum):
    OWN = "own"            # marketplace only: market_type, language, username, password, ...
    SHARED = "shared"      # default for the marketplace's items (option(...) fields)
    LOCATION = "location"  # shared, and part of the location group (option(..., location=True))


@dataclass(frozen=True)
class FieldGuide:
    name: str
    determine: str             # how to work out the value from the user's description
    format: str                # accepted values and examples
    default: str | None = None # what to use when the user does not say ("leave unset" if None)
    secret: bool = False       # never sent to, or set by, the LLM except as a ${VAR} reference


@dataclass
class SectionDraft:
    section_type: str
    name: str
    is_new: bool
    request: str | None
    values: Dict[str, Any]                 # own fields + shared values, as one section
    varies: Dict[str, Dict[str, Any]]      # shared field -> {item name: value} when items differ
    notes: Dict[str, str]                  # field -> short explanation from the LLM


@dataclass
class TurnResult:
    draft: SectionDraft
    question: str | None                   # at most one, only for essentials
    complete: bool


class SectionBuilder:
    section_type: str                      # "marketplace"
    playbook: str                          # "marketplace"
    config_class: type                     # FacebookMarketplaceConfig
    guides: Tuple[FieldGuide, ...]
    uses_ai: bool = True

    def group(self, field: str) -> FieldGroup          # from dataclass metadata, never hand-written
    def context(self, expanded: Dict[str, Any]) -> Dict[str, List[str]]   # names of users, ais, ...
    def view(self, expanded: Dict[str, Any], name: str) -> SectionDraft
    def validate(self, values: Dict[str, Any], context: Dict[str, List[str]]) -> List[str]
    def apply(self, expanded: Dict[str, Any], draft: SectionDraft) -> Dict[str, Any]
    async def converse(self, ui: SetupUI, ctx: BuilderContext, name: str | None) -> int


BUILDERS: Dict[str, SectionBuilder] = {"marketplace": MarketplaceBuilder()}
```

`BuilderContext` carries the config files, `system_cfg`, the user config dict, the backup
directory, the loaded playbooks, and the chosen `AIBackend`.

Rules enforced by tests:

- Every field of `FacebookMarketplaceConfig` except `name` and runtime fields (`monitor_config`)
  has exactly one `FieldGuide`, and no guide names a field that does not exist.
- `group()` reads `option(...)` metadata: a field with `FALLBACK` metadata is SHARED, plus
  LOCATION when it has `LOCATION` metadata; every other field is OWN. `search_region` (fallback
  `None`, `location=True`) is LOCATION.

The existing AI setup stays as it is (scripted, not a `SectionBuilder`).

## 2. Playbooks and field guides

### Content split

- **Playbooks** (markdown) carry the narrative and workflow rules.
- **Field guides** (Python, in `configure/marketplace.py`) carry per-field facts, so a test can
  check their coverage.

### Playbook files

Markdown with simple `key: value` frontmatter between `---` lines (no YAML dependency):

```markdown
---
section: marketplace
summary: Defaults for searching one marketplace (location, filters, schedule, notifications).
---
## Overview
<plain-language description shown to the user as the opening prompt>

## Workflow
<rules for the LLM>
```

- `section` and `summary` are required. `AGENT.md` has `section: base`.
- `## Overview` is required for section playbooks; it is the text shown to the user first.
- Bundled playbooks live in `configure/playbooks/` and ship as package data.
- **House rules:** `~/.ai-marketplace-monitor/playbooks/<name>.md` (same file name) is appended
  under `## House rules (from <path>)`. It may override `summary` only. A user playbook with no
  bundled counterpart is ignored with a warning. Bundled rules cannot be removed.

### `AGENT.md` (every section)

- Reply only with one JSON object:
  `{"request": str, "values": {field: value}, "unset": [field], "notes": {field: str},
  "question": str | null, "complete": bool}`.
- Fill as many fields as you can from the user's description; prefer the defaults in the field
  guide over asking. Explain each value you set in one short phrase in `notes`.
- Ask at most one `question`, and only when an essential value cannot be inferred (for a
  marketplace: no location at all).
- `request` is a one- or two-sentence summary of everything the user has asked for so far, in the
  user's terms. Never a transcript.
- Never invent, ask for, or repeat secrets. Fields marked secret may only be set to a `${VAR}`
  reference, and only when the user asks.
- Only reference names listed in the context (users, AI services, regions, translations).
- Set `complete: true` when the description is captured and no essential value is missing. The
  user still reviews and confirms the section.

### `marketplace.md`

- **Overview** (shown to the user):

  > A marketplace sets the defaults for everything you search on Facebook Marketplace: where to
  > search (your city, how far, or a whole region), who gets notified and which AI rates listings,
  > which listings to consider (condition, delivery, how recent, price range), and how often to
  > search. Items can override any of these.
  >
  > Describe what you want in a few sentences, e.g. "I'm in Houston, search within 40 miles, only
  > local pickup, used items in good condition or better, check every 30 minutes during the day,
  > notify me."

- **Workflow** (for the LLM): values are defaults for every item of this marketplace and items may
  override them; only `facebook` is supported; work out, in order of importance, the location,
  then `notify` / `ai`, then filters, then the schedule; leave everything else unset; Facebook
  login is optional and handled outside the conversation (tell the user about
  `FACEBOOK_USERNAME` / `FACEBOOK_PASSWORD` if they mention logging in).

### Field guides

Every field gets a guide; the table lists the guidance in short form. `rating`, `availability`,
`delivery_method` and `date_listed` also accept a list of two values, for the first search and for
later searches (see "First and subsequent searches" in the README); guides say so. Accepted values come from
the config classes and must stay in sync with them (tests check enum-valued fields against their
enums).

| Field | Group | Determine | Format / default |
|---|---|---|---|
| `market_type` | OWN | always Facebook | `"facebook"`; default: leave unset |
| `language` | OWN | only when listings are not in English; must match a `[translation.X]` | e.g. `"es"`; default: unset |
| `login_wait_time` | OWN | only if the user mentions slow manual login | seconds, int; default: unset |
| `username`, `password` | OWN, **secret** | never from the LLM; only `${FACEBOOK_USERNAME}` / `${FACEBOOK_PASSWORD}` if the user asks | `${VAR}`; default: unset |
| `enabled` | OWN | only when the user wants to pause this marketplace | bool; default: unset |
| `search_city` | LOCATION | the city slug in the Facebook URL `facebook.com/marketplace/<slug>/`; from the user's city | list of strings, e.g. `["houston"]` |
| `city_name` | LOCATION | display names for the cities, same length as `search_city` | list of strings; default: unset |
| `radius` | LOCATION | search radius around each city, as Facebook's distance filter | list of ints, one per city or one for all |
| `currency` | LOCATION | only when listings use a non-default currency | list of currency codes, e.g. `["USD"]`; default: unset |
| `search_region` | LOCATION | when the user wants a whole country/area; must name a defined region | list of region names, e.g. `["usa"]` |
| `notify` | SHARED | who should be told; names of `[user.*]` sections | list; default: all users (leave unset) |
| `ai` | SHARED | which AI services rate listings; names of `[ai.*]` sections | list; default: all (leave unset) |
| `exclude_sellers` | SHARED | sellers to ignore | list of names; default: unset |
| `seller_locations` | SHARED | only sellers from these places | list of strings; default: unset |
| `availability` | SHARED | in-stock / out-of-stock listings | any of `all`, `in`, `out`; default: unset |
| `condition` | SHARED | acceptable conditions | any of `new`, `used_like_new`, `used_good`, `used_fair` |
| `date_listed` | SHARED | how recent listings must be | one of `0`, `1`, `7`, `30` (days; 0 = any time) |
| `delivery_method` | SHARED | pickup / shipping | one of `local_pick_up`, `shipping`, `all` |
| `category` | SHARED | only if every item is in one category | one `Category` value, e.g. `"vehicles"`; default: unset |
| `sort_by` | SHARED | listing order | one of `suggested`, `new`, `price_ascend`, `price_descend`, `distance_ascend` |
| `min_price`, `max_price` | SHARED | price range for all items (rare at marketplace level) | string, e.g. `"100"` or `"100 USD"`; default: unset |
| `search_interval`, `max_search_interval` | SHARED | how often to search; a maximum makes the interval random in between | duration string, e.g. `"30m"`, `"1h 30m"`, `"1d"` |
| `start_at` | SHARED | fixed search times; overrides `search_interval` | list of `"HH:MM[:SS]"` (daily), `"*:MM[:SS]"` (hourly), `"*:*:SS"` (every minute) |
| `rating` | SHARED | minimum AI rating to notify | list of ints 1–5, e.g. `[4]` |
| `prompt`, `extra_prompt`, `rating_prompt` | SHARED | only when the user asks to change how the AI judges listings | free text; default: unset |

The LLM also receives a **context** block: the names of `[user.*]`, `[ai.*]`, `[region.*]` and
`[translation.*]` sections, the marketplace's items, and for each SHARED field either its one
value or "varies" with the per-item values.

## 3. Conversation loop

`SectionBuilder.converse(ui, ctx, name)`:

1. **Start.** Load the config, `expand()` it, build the draft with `view()`.
   - New section: show the playbook's `## Overview` and ask for a description
     (`ui.ask_text`).
   - Existing section: describe it in plain words (values plus `request`), then ask "What would you
     like to change?"
2. **Turn** (`llm.run_turn(ai, instructions, draft, context, answer, history)`):
   - The message contains the instructions (AGENT.md + playbook + house rules + guide table), the
     masked draft, the context, the user's latest text, and the previous turns as
     (aimm summary, user text) pairs. No secrets are ever included.
   - The reply is parsed as JSON; `values` and `unset` are merged into a candidate.
   - The candidate is validated by `builder.validate()`: the config class loads it, referenced
     names exist in the context, secret fields hold only `${VAR}` references (otherwise the field
     is dropped and the LLM told).
   - On bad JSON or validation errors, the errors go back to the LLM, up to 2 retries. If it still
     fails, the user sees "I couldn't turn that into a valid section; please rephrase" and the
     draft is unchanged.
3. **Review.** Show the section as TOML with its `request`, a one-line note per value, any items
   whose values will change, and the LLM's question if any. For a SHARED field that varies, add
   one sentence, e.g. "Your items search different cities (bike: houston, sofa: dallas); I'll
   change only those using houston — say 'all items' to change every one."
   Then: "Anything to adjust? Describe changes in your own words, or press Enter to accept."
4. **Adjust.** A non-empty reply (other than an acceptance such as "yes" / "looks good") is the
   next turn's input; go to 2. The LLM resolves "all items" into the draft's per-field choice.
5. **Accept.** Enter or an acceptance applies the draft (`apply()`) and commits it (section 4).
   A declined write returns to step 3.
6. **Exit** 0 after writing. `/show` re-displays the section, `/quit` and Ctrl-C exit 0 without
   writing. After 15 LLM turns aimm stops calling the LLM and offers to accept or quit.

## 4. Applying and writing

### 4A. Normalize change (prerequisite)

`push_down` removes a marketplace's shared options **only when the marketplace has at least one
item**. A marketplace with no items keeps them in the expanded form, as the defaults its future
items will inherit. `compact()` already leaves them alone (it hoists only for two or more items).
`check_equivalent` is unaffected: with no items the values have no runtime effect. The normalize
spec's push-down rule gets the same one-line change, with tests.

### 4B. `MarketplaceBuilder.apply(expanded, draft)`

Returns a new expanded config (the input is not mutated):

- OWN fields and `request` go into `[marketplace.NAME]` (created when new); `unset` removes keys.
- No items bound to this marketplace: SHARED and LOCATION fields stay on the marketplace.
- With items: for each changed SHARED field, set the new value on every item that held the
  previous marketplace-wide value (the value shared by all its items); items with their own value
  keep it. For a field that varied, apply to the items the user chose (by default, those holding
  the most common value). LOCATION fields are applied as a group, so an item never ends up with a
  mix of old and new location keys.

### 4C. `commit_config(ui, new_expanded, files, system_cfg, backup_dir) -> CommitOutcome`

1. `normalize(new_expanded, system_cfg)`; its `check_equivalent` guards correctness.
2. **One user config file:** render the whole normalized config with `dump_config_toml`.
   **Several files:** take the sections that differ between the old and new normalized configs
   (the marketplace and any changed items), and write each with tomlkit into the last file that
   defines it; new sections go to the marketplace's file, or the first file.
3. Preview a unified diff per target file; confirm ("Write these changes?").
4. Back up each target (mode 0600, `~/.ai-marketplace-monitor/backups`), write, then reload all
   files and compare the effective values with the new expanded config. A later file overriding
   a written key is reported as today (`FAILED`, naming the file and keys).
5. Return `WRITTEN`, `DECLINED` or `FAILED`.

With one file, comments in it are lost (the backup keeps them); the preview says so.

### 4D. Entry points

- `aimm-configure marketplace`: no marketplace yet → propose `[marketplace.facebook]`; one →
  edit it; several → choose one or create a new one.
- `aimm-configure marketplace.NAME`: edit or create that marketplace.
- The front-door menu gains "Marketplace".
- Every path calls `require_usable_ai` first and offers AI setup when no AI works.
- `validate_section_address` accepts `marketplace` and `marketplace.<name>`.

## Errors

| Situation | Behavior |
|---|---|
| No usable AI | offer AI setup; exit 0 if the user quits, 1 if setup fails |
| Config invalid (does not load / expand) | show the error; exit 1; nothing written |
| LLM call fails (network, auth) | show a scrubbed error; offer retry or quit |
| LLM output invalid after retries | tell the user to rephrase; draft unchanged |
| Write declined | back to review |
| Write failed / overridden by another file | show the reason; exit 1 |
| Ctrl-C, `/quit` | "Cancelled."; exit 0; nothing written |

## Testing

- Field guides cover every field; groups match metadata; enum formats match the enums.
- Playbooks: frontmatter parsing, house rules appended, unknown user playbooks ignored, overview
  required.
- `run_turn`: JSON parsing, validation errors fed back, retry limit, secrets masked in the
  prompt, secret fields set to non-`${VAR}` values dropped.
- `apply`: no items; items all inheriting; an item with its own value; a varying field; location
  keys as a group.
- Normalize: a no-items marketplace keeps shared options through expand and normalize.
- `commit_config`: single file (normalized rewrite, backup, diff), several files (section writes
  into defining files), declined, overridden.
- `converse`: full sessions with a scripted fake LLM (canned JSON per turn) and `ScriptedSetupUI`:
  new marketplace, update with adjustment, invalid-then-valid output, quit.
- `AIBackend.chat` for OpenAI-compatible and Anthropic clients, mocked.
- Live check (manual, not in CI): a simulated `aimm-configure marketplace` session with UnitySVC
  against a temporary config file.

## Documentation

- `docs/usage.rst`: `aimm-configure marketplace`, with an example description and the review loop.
- CHANGELOG entry under Unreleased.
- The normalize spec's push-down rule (section 4A).
