"""Reusable interactive configuration dispatcher."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Tuple

from ..ai import AIBackend
from ..config import supported_ai_backends
from ..utils import amm_home
from .agent import ServiceError, run_agent
from .ai_kit import AIToolkit
from .ai_setup import configure_ai, load_ai_sections, probe_sections
from .item import ItemToolkit
from .marketplace import MarketplaceToolkit
from .notify import NotificationToolkit, UserToolkit
from .small_kits import MonitorToolkit, RegionToolkit, TranslationToolkit
from .toolkits import SINGLETONS, Toolkit, section_label
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


_SUPPORTED = (
    "'ai', 'ai.<name>', 'marketplace', 'marketplace.<name>', 'item', 'item.<name>', "
    "'notification', 'notification.<name>', 'user', 'user.<name>', 'region', "
    "'region.<name>', 'translation', 'translation.<name>', and 'monitor'"
)


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
    if family in ("marketplace", "item", "notification", "user", "region", "translation"):
        section_name(section)
        return
    if section == "monitor":  # one unnamed section
        return
    raise ConfigureAddressError(f"Only {_SUPPORTED} are supported for now.")


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


async def default_ai_works(ui: SetupUI, config_files: List[Path]) -> bool:
    """Try the default AI; a broken one cannot help fix the AI sections."""
    sections = [s for s in load_ai_sections(config_files) if s.enabled]
    await ui.say(f"Checking [ai.{sections[0].name}]...", kind="progress")
    [result] = await probe_sections(sections[:1])
    if not result.ok:
        await ui.say(f"{result.message}. Using the AI setup menus instead.", kind="warning")
    return result.ok


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
        # with a working default AI, the AI helps; otherwise the wizard, which needs no AI
        backend, _problem = default_ai(config_files)
        if backend is None or not await default_ai_works(ui, config_files):
            return await configure_ai(
                ui, config_files, section_name=ai_section_name(section), home=home
            )
        await ui.say(f"Using [ai.{backend.config.name}].", kind="progress")
        return await run_session(
            ui,
            config_files,
            backend,
            {"ai": toolkits()["ai"]},
            home=home,
            target=("ai", ai_section_name(section)),
        )
    kits = {family: toolkits()[family]}
    if family == "item":  # an item may need its marketplace created or given a location
        kits["marketplace"] = toolkits()["marketplace"]
    if family in ("notification", "user"):  # users and notifications are set up together
        kits = {t: toolkits()[t] for t in ("notification", "user")}
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
        kits,
        home=home,
        target=(family, section_name(section)),
    )


def toolkits() -> Dict[str, Toolkit]:
    """The section types aimm-configure can edit with the AI, by type."""
    return {
        "ai": AIToolkit(),
        "marketplace": MarketplaceToolkit(),
        "item": ItemToolkit(),
        "notification": NotificationToolkit(),
        "user": UserToolkit(),
        "region": RegionToolkit(),
        "translation": TranslationToolkit(),
        "monitor": MonitorToolkit(),
    }


def system_prompt(ws: Workspace, only_types: List[str] | None) -> str:
    """The instructions: AGENT.md plus the command's guides, or the router and the type list.

    A single-section command gets its section types' playbooks and fields directly (an item
    command also gets the marketplace's, for the item's marketplace); aimm-configure gets the
    router playbook and reads guides with section_guide.
    """
    parts = [ws.playbooks["AGENT"].text()]
    if only_types is not None:
        added: Set[str] = set()  # users and notifications share one playbook
        for section_type in only_types:
            toolkit = ws.toolkits[section_type]
            if toolkit.playbook not in added:
                added.add(toolkit.playbook)
                parts.append(
                    f"# Task: [{section_type}.*] sections\n\n"
                    f"{ws.playbooks[toolkit.playbook].text()}"
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
    """Run the AI over a set of toolkits and return an exit code.

    ``target`` limits it to one section and the sections it depends on (its companions).
    """
    from .mirascope_model import MirascopeModelSession

    home = home or amm_home
    router = target is None
    ws = Workspace(ui=ui, files=list(config_files), home=home, toolkits=kits)
    ws.ai_in_use = ai.config.name  # changes to it take effect the next time
    try:
        await ws.load(["router"] if router else [])
        only: List[Tuple[str, str]] | None = None
        if target is not None:
            section_type, name = target
            chosen = await kits[section_type].choose_target(ui, ws, name)
            if chosen is None:
                return 0
            only = [(section_type, chosen), *kits[section_type].companions(ws, chosen)]

        executor = ToolExecutor(ws, only=set(only) if only else None)
        only_types = list(dict.fromkeys(t for t, _ in only)) if only else None
        executor.guides_read.update(only_types or [])  # their guides are in the prompt
        try:
            model = MirascopeModelSession(
                ai, executor.tools_for_model(), stop=lambda: executor.done
            )
        except ServiceError as e:
            await ui.say(str(e), kind="error")
            return 1
        outcome = await run_agent(
            executor, model, system_prompt(ws, only_types), _opening(ws, only)
        )
    except ConfigLoadError as e:
        await ui.say(str(e), kind="error")
        return 1
    except SetupClosedError:
        return 0
    return 1 if outcome is Outcome.FAILED else 0


def _opening(ws: Workspace, only: List[Tuple[str, str]] | None) -> str:
    if not only:
        return (
            "Command: aimm-configure. The user has not said anything yet. Briefly say what you "
            "can help configure, then ask what they want (ask_user)."
        )
    # the first named section is where to start; "*" allows any section of a type
    command = only[0][0]
    named = [(t, n) for t, n in only if n != "*"]
    anything = [f"any [{t}.*]" for t, n in only if n == "*"]
    if not named:  # e.g. aimm-configure region: no section to start at
        return (
            f"Command: aimm-configure {command}. You may change "
            f"{', '.join(dict.fromkeys(anything))}. Ask the user what they want (ask_user)."
        )
    section_type, name = named[0]
    exists = (
        section_type in ws.user_cfg
        if section_type in SINGLETONS
        else name in ws.user_cfg.get(section_type, {})
    )
    text = (
        f"Command: aimm-configure {command}. The active section is "
        f"{section_label(section_type, name)} ({'existing' if exists else 'new'})."
    )
    others = [section_label(t, n) for t, n in named[1:]] + anything
    if others:
        text += f" You may also change {', '.join(dict.fromkeys(others))} when needed."
    return text + (
        f" Start with section_show(section_type={section_type!r}, name={name!r}), then talk "
        "to the user (ask_user)."
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
