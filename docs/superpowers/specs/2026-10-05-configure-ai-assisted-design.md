# aimm-configure: AI-assisted [ai.*] sections

Builds on [the marketplace design](2026-10-05-configure-marketplace-design.md) and the
notification toolkit (wildcards, `can_apply`, `after_save`).

## Summary

The same operations as the `aimm-configure ai` wizard, driven by the conversation: update or fix a
section, change its model, add a section (which becomes the default unless it is a backup), make
another section the default. The running session keeps its AI; changes take effect on the next
start. `aimm-configure ai` uses this mode when the default AI works and the wizard otherwise; the
router uses the toolkit instead of launching the wizard (`setup_ai` is removed).

## Mapping to the wizard

| Wizard | AI mode |
|---|---|
| Check the default AI | `section_check` returns `trial` from the wizard's `probe_ai_section` (works, message, available models, `suggested_base_url`) |
| Keep / update / fix | `section_update` |
| Make another section the default | virtual `default: true`; save writes the section first |
| New section becomes the default | the same, unless `default: false` (a backup) |
| Model from the provider's list | `available_models` from the probe |
| Key as `${VAR}`, export instructions | same rule; aimm's after-save notes |
| DeepSeek / Gemini: edit by hand | same (existing sections can be kept unchanged) |

## Decisions

- `save` runs `Toolkit.preflight` (the probe): a section that would become the default must work
  or the save is refused; other failures are saved with a warning.
- An `api_key` reference whose variable is not set is refused: aimm cannot load a config with an
  unset AI key, even in a disabled section.
- Literal keys already in the file are masked.
- Writer: `commit_sections(first=...)` places sections first, moving them into the file that holds
  the current first section; the move is text-based, so it works when the type's tables are spread
  through the file.
