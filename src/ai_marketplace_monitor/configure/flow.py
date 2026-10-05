"""Reusable interactive configuration dispatcher."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from ..ai import AIBackend
from ..config import supported_ai_backends
from ..utils import amm_home
from .agent import ServiceError, run_agent
from .ai_setup import AISection, configure_ai, load_ai_sections, probe_sections
from .marketplace import MarketplaceToolkit
from .toolkits import Toolkit
from .tools import Outcome, ToolExecutor
from .ui import SetupClosedError, SetupUI
from .workspace import ConfigLoadError, Workspace
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


def default_ai(config_files: List[Path]) -> Tuple[AIBackend | None, str]:
    """The backend of aimm's default AI (the first enabled ``[ai.*]`` section).

    It is not probed; its Mirascope model is registered. Returns None and the reason if it
    cannot be used.
    """
    from .mirascope_model import model_id

    try:
        sections = [s for s in load_ai_sections(config_files) if s.enabled]
    except ConfigReadError as e:
        return None, str(e)
    if not sections:
        return None, "No AI service is configured yet."
    section = sections[0]
    if section.config is None:
        return None, f"[ai.{section.name}] cannot be used: {section.problem}"
    backend = supported_ai_backends[section.provider](config=section.config)
    try:
        model_id(backend)
    except ServiceError as e:
        return None, str(e)
    return backend, ""


async def ai_for_configure(
    ui: SetupUI, config_files: List[Path], *, home: Path | None = None
) -> AIBackend | None:
    """The AI that assists configuration: the default ``[ai.*]`` section.

    Only if it cannot be used does the user go through ``aimm-configure ai`` (which no AI can
    assist).
    """
    backend, problem = default_ai(config_files)
    if backend is not None:
        await ui.say(f"Using [ai.{backend.config.name}].", kind="progress")
        return backend
    await ui.say(f"{problem} Let's set up an AI service first.", kind="warning")
    if await configure_ai(ui, config_files, home=home):
        return None
    backend, problem = default_ai(config_files)
    if backend is None:
        await ui.say(problem, kind="error")
    return backend


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
    if family in toolkits():
        try:
            ai = await ai_for_configure(ui, config_files, home=home)
        except SetupClosedError:
            return 0
        if ai is None:
            return 1
        return await run_session(
            ui,
            config_files,
            ai,
            {family: toolkits()[family]},
            home=home,
            target=(family, section_name(section)),
        )
    if not await require_usable_ai(ui, config_files):
        return 1
    await ui.say(
        f"Configuring `{family}` sections is not implemented yet.",
        kind="error",
        markdown=True,
    )
    return 1


def toolkits() -> Dict[str, Toolkit]:
    """The section types aimm-configure can edit with the AI, by type."""
    return {"marketplace": MarketplaceToolkit()}


def system_prompt(ws: Workspace, only_type: str | None) -> str:
    """The instructions: AGENT.md plus one type's guide, or the router and the type list.

    A single-section command gets its section type's playbook and fields directly;
    aimm-configure gets the router playbook and reads guides with section_guide.
    """
    parts = [ws.playbooks["AGENT"].text()]
    if only_type is not None:
        toolkit = ws.toolkits[only_type]
        parts.append(
            f"# Task: [{only_type}.*] sections\n\n{ws.playbooks[toolkit.playbook].text()}"
        )
        parts.append(toolkit.guide_table())
    else:
        parts.append(f"# The aimm-configure command\n\n{ws.playbooks['router'].text()}")
        listing = "\n".join(
            f"- `{t}`: {ws.playbooks[k.playbook].summary}" for t, k in ws.toolkits.items()
        )
        parts.append(
            "# Section types you can configure\n\n"
            f"{listing}\n\nRead a type's rules with section_guide before changing it."
        )
    return "\n\n".join(parts)


async def run_session(
    ui: SetupUI,
    config_files: List[Path],
    ai: AIBackend,
    kits: Dict[str, Toolkit],
    *,
    home: Path | None = None,
    target: Tuple[str, str | None] | None = None,
) -> int:
    """Run the AI over a set of toolkits; ``target`` limits it to one section. Exit code."""
    from .mirascope_model import MirascopeModelSession

    home = home or amm_home
    router = target is None
    ws = Workspace(ui=ui, files=list(config_files), home=home, toolkits=kits)
    try:
        await ws.load(["router"] if router else [])
        only = None
        if target is not None:
            section_type, name = target
            chosen = await kits[section_type].choose_target(ui, ws, name)
            if chosen is None:
                return 0
            only = (section_type, chosen)

        async def setup_ai() -> int:
            return await configure_ai(ui, config_files, home=home)

        executor = ToolExecutor(ws, only=only, setup_ai=setup_ai if router else None)
        if only is not None:
            executor.guides_read.add(only[0])  # its guide is in the system prompt
        try:
            model = MirascopeModelSession(
                ai, executor.tools_for_model(), stop=lambda: executor.done
            )
        except ServiceError as e:
            await ui.say(str(e), kind="error")
            return 1
        outcome = await run_agent(
            executor, model, system_prompt(ws, only[0] if only else None), _opening(ws, only)
        )
    except ConfigLoadError as e:
        await ui.say(str(e), kind="error")
        return 1
    except SetupClosedError:
        return 0
    return 1 if outcome is Outcome.FAILED else 0


def _opening(ws: Workspace, only: Tuple[str, str] | None) -> str:
    if only is None:
        return (
            "Command: aimm-configure. The user has not said anything yet. Briefly say what you "
            "can help configure, then ask what they want (ask_user)."
        )
    section_type, name = only
    state = "existing" if name in ws.user_cfg.get(section_type, {}) else "new"
    return (
        f"Command: aimm-configure {section_type}. The active section is "
        f"[{section_type}.{name}] ({state}); only it can be changed. Start with "
        f"section_show(section_type={section_type!r}, name={name!r}), then talk to the user "
        "(ask_user)."
    )


async def configure_front_door(
    ui: SetupUI,
    config_files: List[Path],
    *,
    home: Path | None = None,
) -> int:
    """``aimm-configure``: the AI helps with any section it has tools for."""
    try:
        ai = await ai_for_configure(ui, config_files, home=home)
    except SetupClosedError:
        return 0
    if ai is None:
        return 1
    return await run_session(ui, config_files, ai, toolkits(), home=home)
