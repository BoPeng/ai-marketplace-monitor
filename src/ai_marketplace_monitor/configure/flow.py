"""Reusable interactive configuration dispatcher."""

from __future__ import annotations

from pathlib import Path
from typing import List

from ..ai import AIBackend
from ..config import load_config_dicts, supported_ai_backends
from ..normalize import NormalizeError, expand, normalize
from ..utils import amm_home
from .ai_setup import AISection, configure_ai, load_ai_sections, probe_sections
from .playbooks import PlaybookError, load_playbooks
from .sections import BuilderContext, builders
from .ui import Choice, SetupClosedError, SetupUI
from .writer import ConfigReadError


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


_SUPPORTED = "'ai', 'ai.<name>', 'marketplace', 'marketplace.<name>', 'item', and 'item.<name>'"


def section_name(section: str) -> str | None:
    """The ``<name>`` of ``<type>.<name>``, or ``None`` for a bare section type."""
    if "." not in section:
        return None
    name = section.split(".", 1)[1]
    if not name:
        raise ConfigureAddressError(f"Only {_SUPPORTED} are supported for now.")
    return name


def validate_section_address(section: str) -> None:
    """Validate a section address that the dispatcher knows how to route."""
    family = section_family(section)
    if family == "ai":
        ai_section_name(section)
        return
    if family in ("marketplace", "item"):
        section_name(section)
        return
    raise ConfigureAddressError(f"Only {_SUPPORTED} are supported for now.")


async def require_usable_ai(ui: SetupUI, config_files: List[Path]) -> bool:
    """Return true when an enabled AI section works, checking them in order (first = default)."""
    return await _first_usable_ai(ui, config_files) is not None


async def find_usable_ai(ui: SetupUI, config_files: List[Path]) -> AIBackend | None:
    """The backend of the AI section aimm would use (the default, or the first that works)."""
    section = await _first_usable_ai(ui, config_files)
    if section is None or section.config is None:
        return None
    return supported_ai_backends[section.provider](config=section.config)


async def _first_usable_ai(ui: SetupUI, config_files: List[Path]) -> AISection | None:
    try:
        sections = [section for section in load_ai_sections(config_files) if section.enabled]
    except ConfigReadError as e:
        await ui.say(str(e), kind="error")
        return None
    if not sections:
        await ui.say(
            "Configure a working AI service first with `aimm-configure ai`.",
            kind="error",
        )
        return None

    # aimm uses the first AI section; check the others only if it does not work
    for index, section in enumerate(sections):
        await ui.say(f"Checking [ai.{section.name}]...")
        [result] = await probe_sections([section])
        if result.ok:
            if index:
                await ui.say(
                    f"Your default AI [ai.{sections[0].name}] does not work; using "
                    f"[ai.{section.name}]. Run `aimm-configure ai` to fix it.",
                    kind="warning",
                )
            await ui.say(f"Using [ai.{section.name}] ({result.model}).", kind="success")
            return section
        await ui.say(f"[ai.{section.name}] - {result.message}", kind="warning")

    await ui.say(
        "No usable AI service is available; run `aimm-configure ai` first.",
        kind="error",
    )
    return None


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
    if family in builders():
        return await build_section(ui, config_files, family, section_name(section), home=home)
    if not await require_usable_ai(ui, config_files):
        return 1
    await ui.say(
        f"Configuring `{family}` sections is not implemented yet.",
        kind="error",
        markdown=True,
    )
    return 1


async def build_section(
    ui: SetupUI,
    config_files: List[Path],
    section_type: str,
    name: str | None,
    *,
    home: Path | None = None,
) -> int:
    """Create or update a section with its AI-led builder."""
    ai = await find_usable_ai(ui, config_files)
    if ai is None:
        return 1
    home = home or amm_home
    builder = builders()[section_type]
    warnings: List[str] = []
    try:
        system, user = load_config_dicts(config_files)
        ctx = BuilderContext(
            files=list(config_files),
            system_cfg=system,
            user_cfg=user,
            expanded=expand(user, system, partial=True).config,
            normalized=normalize(user, system, partial=True).config,
            backup_dir=home / "backups",
            playbooks=load_playbooks(
                ["AGENT", builder.playbook], home / "playbooks", warn=warnings.append
            ),
            ai=ai,
        )
    except (ValueError, OSError, NormalizeError, PlaybookError) as e:
        await ui.say(f"Cannot read the configuration: {e}", kind="error")
        return 1
    for warning in warnings:
        await ui.say(warning, kind="warning")
    return await builder.converse(ui, ctx, name)


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
                    Choice(
                        "marketplace",
                        "Marketplace",
                        "where and how to search Facebook Marketplace",
                    ),
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
