---
section: item
summary: What to search for: one [item.NAME] per thing the user wants (phrases, price, extra requests).
---
## Goal

An `[item.NAME]` section that makes aimm find the listings this user wants and notify them about
good ones. An item says what to search for and how to judge listings; everything else (location,
schedule, notifications, filters) comes from its marketplace unless the item overrides it.

## Subtasks

### What to search for

`search_phrases` are what the user would type into Facebook Marketplace's search box: a few
short phrases for the same thing (brand and model, common names). Infer them from the user's
words; do not ask for them unless the item is unclear. Name a new item after it, in one short
word (`action_camera`, `road_bike`).

### What it should be

Put what exactly the user wants into `description`, in plain words: model or generation,
condition, what to avoid. The AI that rates listings reads it, and it is the most effective way
to get good matches. Use `keywords` / `antikeywords` only as hard pre-filters for clear cases
(for example `antikeywords = ["case only", "for parts"]`), since a listing they drop never
reaches the AI.

### Price

`min_price` / `max_price` for this item. Use the user's currency only if they mention one.

### Where and how far

`section_show` returns `inherited_from_marketplace`: what the item uses from its marketplace.
Set a location field on the item only if this item should differ (another city, a different
distance, a whole region); otherwise leave it to the marketplace.

If `marketplace_exists` is false, the item cannot be searched yet: create the marketplace
(`section_update` with `section_type="marketplace"`), following the marketplace task, with the
user's location from a pasted Facebook Marketplace URL and the distance they want. Then later
items inherit it. Tell the user you are setting up the marketplace too.

### Extra requests

Anything else about which listings are good goes into `extra_prompt`, in the user's words:
"skip listings that need repair", "prefer sellers with original packaging", "must include the
charger". It is added to the AI's evaluation instructions. Use `rating` for how picky to be
(4 or 5 to see only good matches). Change `prompt` or `rating_prompt` only if the user
explicitly wants to replace aimm's evaluation or rating instructions.

### Other overrides

Condition, pickup or shipping, how recent, how often to search, who is notified: set them on
the item only if the user wants this item to differ from the marketplace.

## Completion

The item is complete when it has `search_phrases`, its marketplace exists (saved or drafted in
this session), and a location is available from the item or its marketplace. Settings the user
mentioned are set; anything else stays unset so the marketplace's values apply.

## Rules

- Change the marketplace only to create it or to give it a missing location, and say so: its
  values apply to every item.
- Do not set fields to the value the item already inherits.
