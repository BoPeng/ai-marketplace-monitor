---
section: translation
summary: Facebook page labels in another language ([translation.NAME]), for users whose Facebook is not in English.
---
## Goal

aimm reads listings by finding labels such as "Condition" and "Description" on Facebook pages.
When the user's Facebook is in another language, a `[translation.NAME]` section gives those labels
as Facebook shows them, and the marketplace uses it with `language = "NAME"`. aimm has built-in
translations (`built_in_examples` in `section_show`); add one only for another language.

## Subtasks

### The language

Set `locale` to the language name in English ("German"). Name the section with a short code
(`de`).

### The labels

The fields are the English labels aimm looks for. Draft each one in the user's language as
Facebook would show it, then show the user the full list and ask them to open a Facebook
Marketplace listing in their language and correct any label that differs: a label must match the
page exactly, or aimm does not find that part of the page. aimm reminds them before saving.
Labels left unset stay in English.

### Using it

A marketplace uses a translation through its `language` field, which this command does not
change; tell the user to run `aimm configure marketplace` (or ask for it in `aimm configure`).
`section_show` lists `used_by_marketplaces`.

## Completion

A translation is complete when it has a `locale` and the labels the user checked.
