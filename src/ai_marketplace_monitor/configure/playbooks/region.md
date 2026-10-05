---
section: region
summary: Named groups of cities ([region.NAME]) that marketplaces and items search with search_region.
---
## Goal

`[region.NAME]` sections that let a marketplace or item search a whole area at once with
`search_region = "NAME"`. aimm has built-in regions (`section_show` lists them under
`built_in_regions`); the user's own sections add new ones or change a built-in one.

## Subtasks

### A new region

Ask which cities the region covers and how far around each to search. Every `search_city` is a
Facebook location code and is never guessed: for each city, ask the user to open Facebook
Marketplace, set that location, search for anything and paste the URL; the code is the segment
after `/marketplace/` (as in the marketplace task). Codes already in the config or a built-in
region can be reused. Set `city_name` to readable names in the same order, `radius` to one
distance or one per city, and `currency` if the user sets price limits in a currency. Choose a
short name (`gulf_coast`) and a `full_name`.

### Changing a built-in region

A section with a built-in region's name changes it: its values replace the built-in ones
(`built_in` in `section_show` shows them). For "search the USA within 300 miles", set only
`radius` on `[region.usa]`. To change the cities, set all of `search_city`, `city_name` and
`radius`.

### Using it

A region is used by setting `search_region` on a marketplace or item, which this command does not
change; tell the user to run `aimm-configure marketplace` (or ask for it in `aimm-configure`).

## Completion

A region is complete when it has `search_city` (its own or the built-in one), with `city_name`,
`radius` and `currency` either one value or one per city.
