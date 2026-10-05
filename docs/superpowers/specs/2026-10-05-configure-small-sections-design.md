# aimm-configure: [monitor], [region.*] and [translation.*]

Builds on [the marketplace design](2026-10-05-configure-marketplace-design.md) and the later
toolkits (wildcards, `can_apply`, notes after saving).

## Summary

`aimm-configure monitor`, `region[.NAME]` and `translation[.NAME]`, and the same requests in
`aimm-configure`. Each command changes only sections of its own type.

## Decisions

| Topic | Decision |
|---|---|
| `[monitor]` | One unnamed section, keyed `("monitor", "monitor")` and shown as `[monitor]` (`SINGLETONS`, `section_label`). The writer edits it as a top-level table; before, it skipped `monitor` |
| Proxy secrets | `proxy_username` and `proxy_password` only as `${VAR}`; unset variables are listed after saving |
| Regions | A new region needs `search_city`; codes follow the never-guess rule (pasted Marketplace URLs), and codes already in the config or in a built-in region count as given. A section named like a built-in region changes it: validation merges the built-in values first, so `radius = 300` alone is valid. `section_show` lists the built-in regions and shows the built-in values read-only |
| Translations | Fields are `locale`, `enabled` and the English labels aimm looks for (`LABELS`, kept in sync with the `translator(...)` calls by a test). The AI drafts the labels; the save preview reminds the user to compare them with a Facebook listing, since they must match exactly. Built-in translations are shown as examples |
| Using them | `search_region` and `language` live on marketplaces and items; these commands only point the user there |
| No section to start at | `aimm-configure region` / `translation` start without an active section; the opening says which types may change and asks the user |

## Testing

Guide coverage; masking and secrets; `[monitor]` written as one section, listed and labelled;
the restriction to one type; region city codes, built-in override, list lengths; translation
labels in sync with facebook.py, unknown labels, text values, the reminder, saving labels with
apostrophes; start summaries; CLI dispatch.
