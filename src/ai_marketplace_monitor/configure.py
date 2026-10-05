"""Reusable interactive configuration dispatcher."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List

from .ai_setup import (
    Choice,
    ConfigReadError,
    SetupClosedError,
    SetupUI,
    configure_ai,
    load_ai_sections,
    probe_ai_section,
)


class ConfigureAddressError(ValueError):
    """The requested configuration section is not supported."""


def section_family(section: str) -> str:
    """Return the section family for a section address."""
    return section.split(".", 1)[0]


def ai_section_name(section: str) -> str | None:
    """Return the named ``ai`` section suffix, or ``None`` for the ``ai`` group."""
    if section == "ai":
        return None
    if section.startswith("ai."):
        name = section.split(".", 1)[1]
        if name:
            return name
    raise ConfigureAddressError("Only 'ai' and 'ai.<name>' are supported for now.")


def validate_section_address(section: str) -> None:
    """Validate a section address that the dispatcher knows how to route."""
    family = section_family(section)
    if family == "ai":
        ai_section_name(section)
        return
    if family == "item" and section not in ("item.",):
        return
    raise ConfigureAddressError(
        "Only 'ai', 'ai.<name>', 'item', and 'item.<name>' are supported for now."
    )


async def require_usable_ai(ui: SetupUI, config_files: List[Path]) -> bool:
    """Return true when at least one enabled AI section can answer a test request."""
    try:
        sections = [section for section in load_ai_sections(config_files) if section.enabled]
    except ConfigReadError as e:
        await ui.say(str(e), kind="error")
        return False
    if not sections:
        await ui.say(
            "Configure a working AI service first with `aimm-configure ai`.",
            kind="error",
        )
        return False

    await ui.say(f"Checking {len(sections)} AI service(s)...")
    results = await asyncio.gather(
        *(asyncio.to_thread(probe_ai_section, section) for section in sections)
    )
    for section, result in zip(sections, results):
        if result.ok:
            await ui.say(f"Using [ai.{section.name}] ({result.model}).", kind="success")
            return True
        await ui.say(f"[ai.{section.name}] - {result.message}", kind="warning")

    await ui.say(
        "No usable AI service is available; run `aimm-configure ai` first.",
        kind="error",
    )
    return False


async def configure_section(
    ui: SetupUI,
    config_files: List[Path],
    section: str,
    *,
    home: Path | None = None,
) -> int:
    """Configure a specific section address such as ``ai`` or ``ai.openai``."""
    validate_section_address(section)
    family = section_family(section)
    if family == "ai":
        return await configure_ai(
            ui,
            config_files,
            section_name=ai_section_name(section),
            home=home,
        )
    if not await require_usable_ai(ui, config_files):
        return 1
    await ui.say(
        f"Configuring `{family}` sections is not implemented yet.",
        kind="error",
        markdown=True,
    )
    return 1


async def configure_front_door(
    ui: SetupUI,
    config_files: List[Path],
    *,
    home: Path | None = None,
) -> int:
    """Run the primary interactive configure flow."""
    exit_code = await configure_section(ui, config_files, "ai", home=home)
    if exit_code:
        return exit_code

    while True:
        try:
            choice = await ui.choose(
                "What would you like to configure next?",
                [
                    Choice("ai", "AI services", "add or update [ai.*] sections"),
                    Choice("quit", "Quit"),
                ],
                default="quit",
            )
        except SetupClosedError:
            return 0
        if choice == "quit":
            return 0
        exit_code = await configure_section(ui, config_files, choice, home=home)
        if exit_code:
            return exit_code
