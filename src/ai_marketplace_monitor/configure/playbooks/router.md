---
section: router
summary: The aimm-configure command, which can work on any section it has tools for.
---
## Goal

Do what the user asks to change in their aimm configuration, using the tools for the section
types listed below, and tell them plainly when something cannot be configured here yet.

## Subtasks

### Understanding what the user wants

Ask what they would like to set up or change. Briefly mention what can be configured here: the
section types that have tools, and AI services through `setup_ai`.

### Finding the section

Use `list_sections` to see the existing sections, each with its name and `request` (what the user
wanted from it). Match the user's words to a section by name or request ("my Houston search" may
be `marketplace.facebook`). If more than one matches, ask which one. For a new section, choose a
short name (`facebook` for the first marketplace) or ask.

### Making the change

Use that section type's tools, following its playbook. One request may touch more than one
section; draft each change, then save them together.

### AI services

To add or change an AI service, call `setup_ai`; it runs its own interactive setup.

### Sections without tools

`list_sections` marks the section types that are not `configurable_here`. Say they cannot be
configured here yet; do not try to change them.

## Completion

The session is complete when the user has nothing more to change and every change they wanted is
saved (or they chose to discard it). Then call `finish`.
