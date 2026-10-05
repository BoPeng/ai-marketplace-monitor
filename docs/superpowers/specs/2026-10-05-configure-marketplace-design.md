# Design: AI-assisted `aimm-configure marketplace`

**Date:** 2026-10-05
**Status:** Draft, for review

## Summary

`aimm-configure marketplace` (and `marketplace.NAME`) creates or updates a `[marketplace.NAME]`
section through a conversation with an LLM. aimm first shows the existing marketplaces (their
`request` and settings) and lets the user pick one or start a new one. The LLM is then given a
**task**, not a script: from the current situation it works out what is missing, asks the questions
it needs, and fills the section until it is complete and valid; the user reviews the section and
confirms. Only that section is written, edited in place in the file that defines it.

It is the first AI-driven section builder, and it brings back the generic structure designed
earlier (`SectionBuilder`, field guides, playbooks), which was removed before #368 merged because
nothing concrete used it. The item builder will reuse all of it.

Decisions made while designing:

| Topic | Decision |
|---|---|
| Structure | Generic `SectionBuilder` framework; marketplace is its first AI-driven builder |
| Field facts | Each field's group (own / shared with items / location) comes from dataclass metadata; field guides add only human guidance |
| LLM protocol | Structured JSON turns, validated by aimm; provider-agnostic, no tool calling |
| Start | aimm (not the LLM) shows existing marketplaces with their `request` and settings, and asks whether to update one or create a new one |
| Conversation | The LLM gets a task (complete the section: required fields first, then optional fields the user cares about), decides what is missing and what to ask, writes every message, and decides how the conversation ends (`ask` / `save` / `no_change` / `cancel`); aimm validates, enforces completeness, and asks the user to confirm the file change |
| Shared fields with existing items | Items without their own value inherit the new marketplace value; items with their own value keep it. The marketplace builder never edits items (revised: an "apply to every item" option was removed after it changed an item the user meant to keep) |
| Write path | Only the changed sections, edited key by key in place (tomlkit) in the file that defines each; comments and other sections untouched. Revised after a live run: the earlier whole-file normalized rewrite moved settings in unrelated sections and dropped comments |

## The pattern for every section builder

Each `aimm-configure` subcommand modifies **one** existing section or creates one new section, and
nothing else:

- **Writes:** only `[<type>.<name>]`, edited in place in the file that defines it.
  `commit_sections(..., only=[(type, name)])` refuses a result that differs anywhere else, so a
  builder cannot change another part of the config even by mistake.
- **LLM input:** only that section (empty for a new one) and the names it may use as values
  (e.g. users for `notify`); never other sections' contents. This keeps the conversation focused.
- aimm itself (not the LLM) may read other sections to validate the result and to inform the
  user (e.g. which items keep their own values).

## Goals and non-goals

Goals:

- `aimm-configure marketplace` / `marketplace.NAME` creates or updates a marketplace section through
  an LLM-led conversation, then exits after the user confirms and the file is written.
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
    default: str | None = None # what happens at runtime when the field is unset
    secret: bool = False       # never sent to, or set by, the LLM except as a ${VAR} reference


@dataclass
class SectionDraft:
    section_type: str
    name: str
    is_new: bool
    request: str | None
    values: Dict[str, Any]                 # own fields + shared values, as one section
    varies: Dict[str, Dict[str, Any]]      # shared field -> {item name: value} when items differ


@dataclass
class TurnResult:
    draft: SectionDraft
    message: str                           # what the LLM says to the user (questions included)
    action: str                            # "ask" | "save" | "no_change" | "cancel", by the LLM


class SectionBuilder:
    section_type: str                      # "marketplace"
    playbook: str                          # "marketplace"
    config_class: type                     # FacebookMarketplaceConfig
    guides: Tuple[FieldGuide, ...]
    uses_ai: bool = True

    def group(self, field: str) -> FieldGroup          # from dataclass metadata, never hand-written
    def context(self, ctx, draft) -> Dict[str, Any]       # names of users, ais, items, ...
    def view(self, ctx, name: str) -> SectionDraft        # the section as written
    def validate(self, values: Dict[str, Any], context: Dict[str, List[str]]) -> List[str]
    def missing(self, draft: SectionDraft) -> List[str]   # required gaps, decided in code
    def describe(self, draft: SectionDraft) -> str         # request + section as TOML, for the user
    def apply(self, ctx, draft) -> Dict[str, Any]         # user config with the section replaced
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

**Completeness** is decided in code, not by the LLM: a draft is complete when `validate()` returns
no errors and `missing()` is empty. For a marketplace, `missing()` requires a location: a shared
`search_city` or `search_region`, or, when the marketplace has items, a location on every item
(`varies` counts). Every other field is optional.

The existing AI setup stays as it is (scripted, not a `SectionBuilder`).

## 2. Playbooks and field guides

### Content split

- **Playbooks** (markdown) describe a **task**: its goal, how to achieve each subtask, and the
  rules for completion. They are never a transcript or script: they do not say what to say or in
  which order to ask. This is the method for **every** section builder (marketplace now; item,
  user, notification and the rest later), each with its own playbook in the same structure.
- **Field guides** (Python, in `configure/marketplace.py`) carry per-field facts, so a test can
  check their coverage.

### Playbook files

Markdown with simple `key: value` frontmatter between `---` lines (no YAML dependency):

```markdown
---
section: marketplace
summary: Defaults for searching one marketplace (location, filters, schedule, notifications).
---
## Goal
<what the finished section achieves for the user>

## Subtasks
### <subtask>
<what it decides, how to work it out (what to infer, what to ask, which fields), pitfalls>

## Completion
<rules for when the section is complete; the minimum is a valid section that can be added to the
config>

## Rules
<constraints: what not to touch, secrets, interactions with other sections>
```

- `section` and `summary` are required. `AGENT.md` has `section: base` and holds the shared
  method and reply format.
- Section playbooks must have `## Goal`, `## Subtasks` and `## Completion`; `## Rules` is
  optional. The loader rejects a section playbook missing a required heading.
- `## Completion` describes the rules for the LLM; the builder's `missing()` enforces the same
  required parts in code (a test keeps the two in step by checking that every requirement
  `missing()` can report is named in `## Completion`).
- Bundled playbooks live in `configure/playbooks/` and ship as package data.
- **House rules:** `~/.ai-marketplace-monitor/playbooks/<name>.md` (same file name) is appended
  under `## House rules (from <path>)`. It may override `summary` only. A user playbook with no
  bundled counterpart is ignored with a warning. Bundled rules cannot be removed.

### `AGENT.md` (every section)

- You are helping a user configure one section of aimm. You get: the task (section playbook: goal,
  subtasks, completion rules), the
  field guides, the current section, the situation (new or existing, its `request`, related
  sections and items), what is still required, and the conversation so far.
- Each turn, evaluate what is known, what is still required, and which optional settings would
  likely matter to this user; then decide what to ask. Ask the few questions that matter most, in
  plain language the user understands without knowing aimm's field names, and offer sensible
  choices. Do not walk through fields one by one.
- Set every value you can infer from what the user said; do not ask about what you can infer.
- Reply only with one JSON object:
  `{"action": "ask" | "save" | "no_change" | "cancel", "message": str, "request": str,
  "values": {field: value}, "unset": [field]}`. `message` is shown to the user as is: your
  question, or a short summary of the section.
- `request` is a one- or two-sentence summary of everything the user has asked for so far, in the
  user's terms. Never a transcript.
- You decide how the conversation continues from what the user says: `ask` for more, `save`
  when the section is complete and the user is happy, `no_change` to keep it, `cancel` to stop.
  aimm checks completeness itself before saving, and asks the user to confirm the file change.
- Never invent, ask for, or repeat secrets. Fields marked secret may only be set to a `${VAR}`
  reference, and only when the user asks.
- Only reference names listed in the context (users, AI services, regions, translations).

### `marketplace.md`

- **Goal:** a marketplace section holding the defaults for searching Facebook Marketplace (the
  only supported marketplace) that fit how this user shops. Shared values apply to every item of
  the marketplace unless an item sets its own; own values (language, login) apply to the
  marketplace itself.
- **Subtasks:**
  - *Location* (required): where to search. Infer the city and distance from what the user says;
    a whole country or area maps to a defined region. City names must become Facebook's city
    slug.
  - *Who and how*: who is notified (`notify`) and which AI services rate listings (`ai`). The
    defaults (all users, all AI services) are usually right; change them only if the user has
    several of either and a preference.
  - *Which listings*: condition, delivery method, how recent, availability, sort order, and a
    price range only if it applies to everything the user searches here. Ask only about what is
    likely to matter for this user.
  - *Schedule*: how often to search, or fixed times. Leave unset unless the user cares.
  - *Updating an existing section*: start from its `request` and values; find out what to change;
    keep everything else.
  - *Items*: this section never changes items; a marketplace value is a default that items
    without their own value use. The LLM sees only item names, not their values.
- **Completion:** the section loads as a valid marketplace config and has a location (a shared
  city or region, or a location on every item). Optional settings the user mentioned are set;
  anything not discussed stays unset so aimm's defaults apply.
- **Rules:** Facebook login is optional and handled outside the conversation; if the user brings
  it up, explain `FACEBOOK_USERNAME` / `FACEBOOK_PASSWORD`, and never set `username` / `password`
  to anything but those references.

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

### 3A. Start (aimm, no LLM)

1. `require_usable_ai` picks a working AI (offering AI setup when none works).
2. Load and `expand()` the config.
3. **Existing marketplaces are shown first.** For each `[marketplace.*]`: its name, its `request`
   (when set), its settings as TOML (secrets masked), and its number of items. Then ask:
   - one or more exist: "Update one of these, or create a new marketplace?" (`ui.choose` with each
     marketplace, "Create a new marketplace", and Quit);
   - none exist: say so and start a new one;
   - `aimm-configure marketplace.NAME`: show that section when it exists (or say it is new) and
     continue with it.
4. A new marketplace gets a name: `facebook` when free, otherwise the user is asked
   (`ui.ask_text`, default `facebook_2`).
5. Build the draft with `view()`.

### 3B. LLM-led conversation

Each round is one LLM turn, `llm.run_turn(ai, instructions, situation, history)`:

- **Instructions:** `AGENT.md`, the section playbook (goal, subtasks, completion, rules), house
  rules, and the field-guide table grouped by `FieldGroup`.
- **Situation** (rebuilt every turn): new or existing; the current draft (secrets masked) and its
  `request`; what is still required (`missing()`); the context (names of users, AI services,
  regions, translations): the values it may reference. The LLM is given only this section and
  those names, never other sections' contents.
- **History:** previous LLM messages and user replies, in order.

The reply (`action`, `message`, `request`, `values`, `unset`) is parsed and the candidate draft validated (`validate()`: the
config class loads it, referenced names exist, secret fields hold only `${VAR}` references, the
whole config still loads). Bad JSON, an unknown `action` or validation errors go back to the LLM,
up to 2 retries; if it still fails the user is told "I couldn't turn that into a valid section;
please try saying it differently" and the draft is unchanged.

**The LLM decides how the conversation continues** through `action`; aimm only carries it out,
and never interprets the user's words itself. Every user reply goes to the LLM.

| `action` | aimm does |
|---|---|
| `ask` | show `message` (the question), read the reply, next turn |
| `save` | if `missing()` is not empty, tell the LLM what is missing (next turn, no user prompt); otherwise show `message` and the section (`describe()`), then `commit_sections` (diff and one "Write these changes?" confirmation). Declined: ask "What would you like to change?" and continue |
| `no_change`, `cancel` | show `message`, write nothing, exit 0 |

For a new section the first turn is the LLM's: it opens the conversation itself; for an existing
one it starts from the `request` and values and asks what to change.

Commands in any reply: `/show` displays the current draft, `/quit` (or Ctrl-C) exits 0 without
writing. After 15 LLM turns aimm stops calling the LLM: it shows the draft and offers to save it
(only when complete) or quit.

## 4. Applying and writing

### 4A. Normalize change (prerequisite)

`push_down` removes a marketplace's shared options **only when the marketplace has at least one
item**. A marketplace with no items keeps them in the expanded form, as the defaults its future
items will inherit. `compact()` already leaves them alone (it hoists only for two or more items).
`check_equivalent` is unaffected: with no items the values have no runtime effect. The normalize
spec's push-down rule gets the same one-line change, with tests.

The monitor requires `[marketplace]`, `[user]` and `[item]` sections, but a config being built with
aimm-configure usually lacks some of them (the first marketplace is written before any item).
`Config.from_dicts`, `expand()` and `normalize()` therefore take `partial=True`, which skips only
that required-sections check; aimm-configure always uses it. Empty section groups are dropped
from the result.

### 4B. `MarketplaceBuilder.view` and `apply` (revised)

The draft is the marketplace section **as the user wrote it** (merged across files), not a view of
the expanded config. Items' own values for shared fields are kept separately
(`SectionDraft.item_overrides`); aimm (not the LLM) uses them to tell the user which items keep
their own values. They are not sent to the LLM.

`apply()` returns the user config with `[marketplace.NAME]` replaced by `request` + the draft
values. Items are never changed: they use marketplace values unless they set their own; changing
an item belongs to the item builder. `validate()` loads the result
(`expand(..., partial=True)`) to catch cross-section errors.

### 4C. `commit_sections(ui, new_user_cfg, old_user_cfg, files, backup_dir) -> CommitOutcome`

1. The changed sections are those that differ between the old and new user configs.
2. Each is edited key by key with tomlkit in the last file that defines it (new sections go to the
   last config file); comments, order and other sections are kept.
3. Preview a unified diff per file; confirm; back up (mode 0600); write.
4. Reload and check each changed section reads back as written; a later file overriding keys is
   reported (`FAILED`).
5. Nothing changed: say so and write nothing. A draft whose values are unchanged (only the LLM's
   `request` differs) is not written either.

The section-4A normalize changes (item-less marketplaces keep options; `partial=True`) remain:
`partial` is used for validation, as the config may not have every section yet.

### 4D. Entry points

- `aimm-configure marketplace`: show existing marketplaces and choose one or a new one (3A).
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
- Playbooks: frontmatter parsing, house rules appended, unknown user playbooks ignored, required
  headings (`Goal`, `Subtasks`, `Completion`) enforced, `missing()` requirements named in
  `## Completion`.
- `run_turn`: JSON parsing, validation errors fed back, retry limit, secrets masked in the
  prompt, secret fields set to non-`${VAR}` values dropped.
- Completeness: `missing()` for no location / shared location / per-item locations; an LLM
  `save` with missing fields goes back to the LLM, not to the user.
- Start: existing marketplaces listed with `request` and settings; choose existing / new / quit.
- `apply`: no items; items all inheriting; an item with its own value; a varying field; location
  keys as a group.
- Normalize: a no-items marketplace keeps shared options through expand and normalize.
- `commit_config`: single file (normalized rewrite, backup, diff), several files (section writes
  into defining files), declined, overridden.
- `converse`: full sessions with a scripted fake LLM (canned JSON per turn) and `ScriptedSetupUI`:
  new marketplace, update an existing one, "No" at review then a change, invalid-then-valid
  output, quit.
- `AIBackend.chat` for OpenAI-compatible and Anthropic clients, mocked.
- Live check (manual, not in CI): a simulated `aimm-configure marketplace` session with UnitySVC
  against a temporary config file.

## Documentation

- `docs/usage.rst`: `aimm-configure marketplace`, with an example description and the review loop.
- CHANGELOG entry under Unreleased.
- The normalize spec's push-down rule (section 4A).
