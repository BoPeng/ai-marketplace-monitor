---
section: marketplace
summary: Defaults for searching Facebook Marketplace (location, notifications, filters, schedule).
---
## Goal

A `[marketplace.NAME]` section that holds the defaults for searching Facebook Marketplace (the
only supported marketplace) and fits how this user shops. Its shared values apply to every item of
this marketplace unless an item sets its own value; its own values (language, login) apply to the
marketplace itself.

## Subtasks

### Location (required)

Where to search. Infer the city and how far to search from what the user says; ask only if no
place is mentioned. `search_city` is the city's slug in Facebook's URL
(`facebook.com/marketplace/<slug>/`), usually the city name in lowercase without spaces, e.g.
`houston`, `sanfrancisco`, `nyc`; add `city_name` with the readable name. `radius` is the search
distance. A whole country or area maps to a defined region (`search_region`), which replaces the
city settings; only use region names from the context.

### Who and how

`notify` (which users are told) and `ai` (which AI services rate listings). The defaults, all users
and all AI services, are usually right: leave them unset unless the user has several users or AI
services and a preference.

### Which listings

Condition, delivery method, how recent listings are, availability, sort order, and a price range
only if it applies to everything the user searches here. Ask only about what is likely to matter
for this user, for example condition and pickup versus shipping for furniture or electronics.

### Schedule

How often to search (`search_interval`, optionally `max_search_interval` for a random interval) or
fixed times (`start_at`). Leave unset unless the user cares; aimm's default is fine for most.

### Updating an existing section

Start from its `request` and values; find out what the user wants to change; keep everything else.

### Items

Only when the context lists items of this marketplace (`items_of_this_marketplace`); otherwise
do not mention items. Say plainly how a change affects them: items that use the
marketplace's value get the new value, items with their own value keep it. If the user wants a
change applied to every item, list the field in an extra reply key `"apply_to_all_items"`, e.g.
`"apply_to_all_items": ["search_city"]`.

## Completion

The section is complete when it loads as a valid marketplace section and it has a location: a
`search_city` or `search_region`, unless every item of the marketplace already has its own
location. Before finishing a new section, ask once about which listings to consider (condition,
pickup or shipping) and how often to search, unless the user already said. Settings the user
mentioned are set; anything not discussed stays unset so aimm's defaults apply.

## Rules

- Logging in to Facebook is optional and happens outside this conversation. If the user brings it
  up, explain that aimm reads `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` from the environment;
  `username` and `password` may only be set to `${FACEBOOK_USERNAME}` / `${FACEBOOK_PASSWORD}`.
- Do not set `market_type`; `facebook` is the default.
