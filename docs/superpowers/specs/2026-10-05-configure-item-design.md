# aimm-configure: the item toolkit

Builds on [the marketplace design](2026-10-05-configure-marketplace-design.md): same tools,
agent loop, Mirascope adapter, playbooks and writer. This adds a second toolkit.

## Summary

`aimm-configure item` / `item.NAME`, and items in `aimm-configure`, let the user describe what
to search for in their own words ("an action camera within $200 and within 20 miles, nothing
that needs repair"). The AI fills `search_phrases`, `description`, the price range and
`extra_prompt` (extra requests in the user's words), and changes the item's marketplace only
when it must exist or needs a location.

## Decisions

| Topic | Decision |
|---|---|
| Inherited values | `section_show(item)` adds `marketplace`, `marketplace_exists` and `inherited_from_marketplace` (masked shared/location values of the item's marketplace, from its draft if any). Read-only |
| Missing marketplace | The item command may also change its marketplace (a companion section): `only = {(item, NAME), (marketplace, M)}` where M is the item's `marketplace`, else the first saved, else the first drafted, else `facebook` |
| Item guides | Own fields (`search_phrases`, `description`, `keywords`, `antikeywords`, `marketplace`, `enabled`) plus every shared field of the marketplace, worded "only if this item should differ" with default "the marketplace's value"; `min_price`, `max_price`, `extra_prompt`, `prompt`, `rating_prompt`, `rating` get item wording. `prompt` / `rating_prompt` only on explicit request |
| Validation | Field formats are checked before `search_phrases` is set (placeholder phrase). References (`notify`, `ai`, `search_region`, `marketplace`) must exist. When phrases are set and the marketplace exists (saved or drafted), the whole config with every other draft must expand (`partial=True`) |
| Completion (`missing`) | `search_phrases`; the marketplace exists; a location (`search_city` or `search_region`) on the item or its marketplace |
| Saving | One confirmation for all drafts; only drafted sections are written |

## Generic changes

- `Toolkit.show_extra(ws, draft)` adds read-only facts to `section_show`; `Toolkit.companions(ws,
  name)` names the other sections a single-section command may change.
- `Workspace.section(type, name)` returns a section's drafted values or saved values;
  `Workspace.config_with_drafts(exclude)` applies every other draft, so validation sees them.
- `ToolExecutor(only=...)` takes a set of sections; a single-section command's system prompt
  includes the playbook and field table of each type it may change.
- `aimm-configure TYPE` accepts only types with a toolkit (`ai`, `marketplace`, `item`).

## Testing

Guide coverage; inherited values; missing marketplace and location; validation before and after
phrases are known; start menu; a scripted session that creates an item and its marketplace in one
save; the restriction to the item and its marketplace; CLI dispatch with both toolkits.
