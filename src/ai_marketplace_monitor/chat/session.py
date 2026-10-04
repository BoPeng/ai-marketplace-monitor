"""A chat session: determine the AI (setting it up if needed), then chat with it."""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Tuple

import tomlkit

from ..ai import AIConfig
from ..config import supported_ai_backends
from ..utils import amm_home
from ..webui.secrets_redact import _is_sensitive
from .ai_sections import (
    AISection,
    ConfigReadError,
    env_var_name,
    load_ai_sections,
    read_toml,
)
from .builders import BUILDERS
from .builders.ai import PROVIDER_LABELS
from .commit import CommitOutcome, commit
from .messages import AskText, Choose, Option, Say
from .playbooks import build_instructions, load_playbooks
from .probe import ProbeResult, probe, scrub
from .sections import ChatContext, SectionRef
from .ui import ChatClosed, ChatUI

HELP = (
    "Commands: `/edit ai` set up or change the AI · `/help` this list · "
    "`/exit` leave (or press Ctrl-D)"
)


_MASK = "<REDACTED>"


def _mask(value: Any, sensitive: bool = False) -> Any:
    """Copy of parsed TOML data with secrets masked, judged by key and by shape."""
    if isinstance(value, dict):
        return {k: _mask(v, sensitive or _is_sensitive(str(k))) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v, sensitive) for v in value]
    if isinstance(value, str):
        if env_var_name(value):
            return value
        return _MASK if sensitive else scrub(value, None)
    return _MASK if sensitive and not isinstance(value, bool) else value


def render_config(files: List[Path]) -> str:
    """The user's config files with secrets masked, for the chat instructions."""
    blocks = []
    for path in files:
        masked = tomlkit.dumps(_mask(read_toml(path)))
        blocks.append(f"`{path}`:\n\n```toml\n{masked.rstrip()}\n```")
    body = "\n\n".join(blocks) if blocks else "(no configuration files yet)"
    return f"# The user's current configuration\n\n{body}"


def _label(section: AISection, result: ProbeResult) -> str:
    provider = PROVIDER_LABELS.get(section.provider, section.provider)
    return f"{section.name} — {provider}, {result.model}"


async def _check_sections(ui: ChatUI, ctx: ChatContext) -> List[Tuple[AISection, ProbeResult]]:
    sections = load_ai_sections(ctx.files)
    enabled = [s for s in sections if s.enabled]
    if enabled:
        await ui.say(Say(f"Checking {len(enabled)} AI service(s)…"))
    results = await asyncio.gather(*(asyncio.to_thread(probe, s) for s in enabled))
    by_name = dict(zip([s.name for s in enabled], results))
    usable = []
    for section in sections:
        result = by_name.get(section.name)
        if result is None:
            await ui.say(Say(f"- {section.name} — disabled"))
        elif result.ok:
            await ui.say(Say(f"✓ {_label(section, result)}", kind="success"))
            usable.append((section, result))
        else:
            await ui.say(Say(f"✗ {section.name} — {result.message}", kind="warning"))
    return usable


async def _edit_ai(ui: ChatUI, ctx: ChatContext, ref: SectionRef) -> AIConfig | None:
    builder = BUILDERS["ai"]
    while True:
        proposal = await builder.converse(ui, ref, ctx)
        if proposal is None:
            return None
        outcome = await commit(ui, proposal, ctx)
        if outcome is CommitOutcome.DECLINED:
            continue
        if outcome is CommitOutcome.FAILED:
            return None
        result = await builder.after_commit(ui, proposal, ctx)
        if result.config is not None:
            return result.config  # type: ignore[no-any-return]
        if not result.retry:
            return None
        ref = proposal.ref


async def _choose_ai(ui: ChatUI, ctx: ChatContext, ref: SectionRef | None) -> AIConfig | None:
    if ref is None:
        usable = await _check_sections(ui, ctx)
        if usable:
            options = [Option(s.name, _label(s, r)) for s, r in usable]
            options += [Option("new", "Set up a different AI…"), Option("quit", "Quit")]
            choice = await ui.ask(
                Choose("Which AI should this chat use?", options, usable[0][0].name)
            )
            if choice == "quit":
                return None
            if choice != "new":
                return next(s.config for s, _ in usable if s.name == choice)
        ref = SectionRef("ai")
    return await _edit_ai(ui, ctx, ref)


def _model(config: AIConfig) -> str:
    backend = supported_ai_backends[(config.provider or config.name).lower()]
    return config.model or str(getattr(backend, "default_model", ""))


async def _chat(ui: ChatUI, ctx: ChatContext, config: AIConfig) -> None:
    backend = supported_ai_backends[(config.provider or config.name).lower()](config=config)
    ctx.ai = backend
    instructions = build_instructions(
        ctx.playbooks,
        ["ai"],
        render_config(ctx.files),
        {"ai": BUILDERS["ai"].guide_text()},
    )
    messages: List[Dict[str, str]] = [{"role": "system", "content": instructions}]
    await ui.say(Say(f"Chatting with {config.name} ({_model(config)}). {HELP}", markdown=True))
    while True:
        text = (await ui.ask(AskText("You"))).strip()
        if not text:
            continue
        if text in ("/exit", "/quit"):
            return
        if text == "/help":
            await ui.say(Say(HELP, markdown=True))
            continue
        if text.split()[0] == "/edit":
            arg = text.split(maxsplit=1)[1] if " " in text else "ai"
            ref = SectionRef.parse(arg)
            if ref.type != "ai":
                await ui.say(
                    Say(f"Chatting about {ref.type} sections isn't available yet.", kind="error")
                )
                continue
            new = await _edit_ai(ui, ctx, SectionRef("ai", ref.name or config.name))
            if new is not None:
                return await _chat(ui, ctx, new)
            continue
        if text.startswith("/"):
            await ui.say(
                Say(f"Unknown command {text.split()[0]}. {HELP}", kind="warning", markdown=True)
            )
            continue
        messages.append({"role": "user", "content": text})
        try:
            reply = await asyncio.to_thread(backend.chat, messages)
        except Exception as e:
            messages.pop()
            detail = scrub(str(e), config.api_key)[:300]
            await ui.say(Say(f"The AI request failed: {detail}", kind="error"))
            continue
        messages.append({"role": "assistant", "content": reply})
        await ui.say(Say(reply, kind="assistant", markdown=True))


async def run_chat(
    ui: ChatUI, config_files: List[Path], target: str | None = None, *, home: Path | None = None
) -> int:
    """Run a chat session; return the process exit code."""
    home = home or amm_home
    ctx = ChatContext(
        files=list(config_files),
        default_file=home / "config.toml",
        playbooks=load_playbooks(user_dir=home / "playbooks"),
        backup_dir=home / "backups",
    )
    try:
        ref = SectionRef.parse(target) if target else None
        if ref is not None and ref.type != "ai":
            await ui.say(
                Say(f"Chatting about {ref.type} sections isn't available yet.", kind="error")
            )
            return 1
        config = await _choose_ai(ui, ctx, ref)
        if config is not None:
            await _chat(ui, ctx, config)
        return 0
    except ChatClosed:
        return 0
    except ConfigReadError as e:
        await ui.say(Say(str(e), kind="error"))
        return 1
