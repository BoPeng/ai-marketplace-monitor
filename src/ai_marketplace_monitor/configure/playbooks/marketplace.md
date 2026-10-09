---
section: marketplace
summary: Defaults for searching Facebook Marketplace (location, notifications, filters, schedule).
---
## Goal

A `[marketplace.NAME]` section that holds the defaults for searching Facebook Marketplace (the
only supported marketplace) and fits how this user shops. Its shared values apply to every item of
this marketplace unless an item sets its own value; its own values (language, login) apply to the
marketplace itself.

The main settings to list whenever you ask what to set or change: where to search (city and distance, or a
region), a price range, condition, pickup or shipping, how recent listings are, how often to
search, and who is notified / which AI rates listings.

## Subtasks

### Location (required)

Where to search: a city (`search_city`) and how far around it (`radius`), or a whole country
or area (`search_region`).

`search_city` is the code Facebook uses for a location in its Marketplace URLs: the path segment
right after `/marketplace/`. It is a name for some large cities (`houston`, `sanfrancisco`,
`nyc`) and a numeric location ID for most other places (`111979382146893`). It cannot be worked
out reliably from a city's name, so never guess it. Instead:

- Ask the user to open Facebook Marketplace in a browser, set the location (and distance) they
  want, search for anything, and paste the URL of the results page.
- Extract the code from the pasted URL: the segment after `/marketplace/` and before the next
  `/` or `?`. Ignore `/search`, `/category/...` and query parameters.
  - `https://www.facebook.com/marketplace/houston/search?query=bike` → `houston`
  - `https://www.facebook.com/marketplace/111979382146893/search/?query=sofa&radius=40` →
    `111979382146893`
  - `https://www.facebook.com/marketplace/bogota/search?minPrice=100000&query=iphone` → `bogota`
- A URL like `https://www.facebook.com/marketplace/` or `.../marketplace/search?...` has no
  location code: ask for the URL after the location is set. A URL from `m.facebook.com` works
  the same way.
- Set `search_city` to the code only (never the whole URL), and `city_name` to the place's
  readable name ("Houston, TX"), from the user or the page title they mention.
- Ask how far to search if they did not say, and set `radius` to that distance. Do not save a
  new location before the user has answered (a distance, or that Facebook's default is fine).
- For several cities, repeat for each; `search_city`, `city_name` and `radius` are lists in the
  same order.

Leave an existing `search_city` as it is unless the user wants another location. A whole country
or area maps to a defined region (`search_region`), which replaces the city settings; only use
region names from the context.

### Who and how

`notify` (which users are told) and `ai` (which AI services rate listings). The defaults, all users
and all AI services, are usually right: leave them unset unless the user has several users or AI
services and a preference.

### Which listings

Condition, delivery method, how recent listings are, availability, sort order, and a price range
only if it applies to everything the user searches here. Ask only about what is likely to matter
for this user, for example condition and pickup versus shipping for furniture or electronics.

### Schedule

How often to search (`search_interval`) or fixed times (`start_at`). Leave unset unless the user
cares; aimm's default is fine for most. When setting `search_interval = X`, tell the user the
actual interval is random between X and 1.5X unless they also set `max_search_interval` (set it
equal to `search_interval` for a fixed interval, or higher for more jitter).

### Updating an existing section

Start from its `request` and values; find out what the user wants to change; keep everything else.

### Items

This section never changes items. A marketplace value is a default: items without their own
value use it, and items with their own value keep it. You do not see items; do not discuss or
offer to change their values. If the user wants to
change an item, tell them this only sets marketplace defaults; an item's own values are changed in
that item's section.

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
