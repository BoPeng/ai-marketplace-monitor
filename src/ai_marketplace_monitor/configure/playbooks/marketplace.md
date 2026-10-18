---
section: marketplace
summary: Defaults for searching a marketplace, Facebook Marketplace or OfferUp (location, notifications, filters, schedule).
---
## Goal

A `[marketplace.NAME]` section that holds the defaults for searching one marketplace and fits how
this user shops. aimm searches two marketplaces:

- **Facebook Marketplace** (`market_type = "facebook"`, the default): aimm logs in with the user's
  Facebook account and searches in a browser.
- **OfferUp** (`market_type = "offerup"`): US only; no account, no login, no browser.

A section named after its marketplace (`[marketplace.facebook]`, `[marketplace.offerup]`) needs no
`market_type`; aimm sets it when it creates a section with another name. Its shared values apply
to every item of this marketplace unless an item sets its own value; its own values (language,
login: Facebook only) apply to the marketplace itself. A new marketplace is also searched by every
item that names no `marketplace`: aimm tells the user when they save it.

The main settings to list whenever you ask what to set or change: where to search (city and distance, or a
region), a price range, condition, pickup or shipping, how recent listings are, how often to
search, and who is notified / which AI rates listings.

## Subtasks

### Location (required)

Where to search: a city (`search_city`) and how far around it (`radius`), or a whole country
or area (`search_region`). `search_city` is in the section's marketplace format: Facebook's code
for the place, or for OfferUp a US ZIP code or the place's coordinates.

#### OfferUp

Ask where to search. A ZIP code the user gives is the value as it is (`search_city = ["77096"]`).
For a city or neighborhood, call `find_city` and confirm the place as below, then use the place's
`offerup` value (its coordinates, e.g. `"29.7604,-95.3698"`). OfferUp offers a radius of 5, 10,
20, 30 or 50 miles (aimm uses the nearest). A region works only if its cities have OfferUp values.

#### Facebook

`search_city` is the code Facebook uses for a location in its Marketplace URLs: the path segment
right after `/marketplace/`. It is a name for some large cities (`houston`, `sanfrancisco`,
`nyc`) and a numeric location ID for most other places (`111979382146893`). It cannot be worked
out reliably from a city's name, so never guess it. Instead:

- Ask where to search: a city, neighborhood or ZIP code, and how far around it. Call
  `find_city` with what the user said, spelled correctly (fix obvious typos; "Los Angles" is
  "Los Angeles"). aimm asks Facebook's location search and returns its matching places, best
  first, each labelled with its region and with its `facebook` code (and `offerup` coordinates).
- Confirm the place with the user from that list before saving, in your own words:
  - one place clearly fits (a ZIP code, or "Houston, TX" → Houston, Texas): ask whether it is
    right;
  - several could be meant: offer them, e.g. "Do you mean Los Angeles, California, Los Angeles
    in Mexico, or Los Ángeles, Chile?" (list the cities, not neighborhoods of the same city);
  - the user's place is not among them (e.g. Los Angeles, Texas is a small town that a search
    for "Los Angeles" does not list): call `find_city` again with the state or country added.
- If `find_city` fails (Facebook's search did not answer), or the user prefers, ask them to
  open Facebook Marketplace in a browser, set the location (and distance) they want, search
  for anything, and paste the URL of the results page.
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
  readable name ("Houston, TX"): the confirmed place from `find_city`, or from the user or the
  page title they mention.
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

Condition, delivery method, how recent listings are, availability (Facebook only), sort order, and
a price range only if it applies to everything the user searches here. OfferUp sections take the
same options except Facebook's (`availability`, `category`, `language`, `currency`, login). Ask only about what is likely to matter
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

- Logging in to Facebook (Facebook sections only) happens outside this conversation. If the user
  brings it up, explain that aimm reads `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` from the
  environment; `username` and `password` may only be set to `${FACEBOOK_USERNAME}` /
  `${FACEBOOK_PASSWORD}`. OfferUp needs no login.
- Leave `market_type` as aimm set it. Change it only if the user wants this section to search
  another marketplace, and then unset the options the new one does not have.
