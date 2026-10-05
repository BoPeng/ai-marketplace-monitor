"""Interactive setup for [ai.*] config sections."""

from __future__ import annotations

import asyncio
import copy
import os
import re
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple, TypeVar

import anthropic
import openai

from .ai import AIBackend, AIConfig, AnthropicBackend, OllamaBackend, OpenAIBackend
from .config import supported_ai_backends
from .config_writer import (
    CommitOutcome,
    ConfigReadError,
    SectionWrite,
    commit_section,
    read_toml,
    render_section,
)
from .setup_ui import Choice, SetupClosedError, SetupUI
from .utils import amm_home, merge_dicts

_PLACEHOLDER = re.compile(r"^\$\{(\w+)\}$")
_SECRET_TOKEN = re.compile(r"(svcpass_|sk-ant-|sk-)[A-Za-z0-9_\-]{4,}")
_TYPED_KEY = re.compile(r"^(svcpass_|sk-ant-|sk-)\S{8,}")
_MARKUP = re.compile(r"\[/?[a-z ]+\]")
_PING = [{"role": "user", "content": "ping"}]
_CONNECTION_ERRORS = (openai.APIConnectionError, anthropic.APIConnectionError)

UNITYSVC_TIERS = ["fast", "balanced", "coding", "premium"]
OLLAMA_URL = "http://localhost:11434/v1"
SHARED_AI_KEYS = {"max_retries", "timeout"}

T = TypeVar("T")


class UnsupportedAISectionError(Exception):
    """The section's provider is not one aimm-configure can set up."""


@dataclass
class AISection:
    name: str
    raw: Dict[str, Any]
    files: List[Path]
    config: AIConfig | None = None
    problem: str | None = None

    @property
    def enabled(self: "AISection") -> bool:
        return self.raw.get("enabled") is not False

    @property
    def provider(self: "AISection") -> str:
        return str(self.raw.get("provider", self.name)).lower()


@dataclass
class ProbeResult:
    ok: bool
    step: str
    model: str
    message: str
    available: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    hint: str
    env_var: str | None
    key_url: str | None


@dataclass
class AISetupContext:
    files: List[Path]
    default_file: Path
    backup_dir: Path


@dataclass
class AISectionProposal:
    name: str
    values: Dict[str, Any]
    request: str | None
    target_file: Path

    def to_write(self: "AISectionProposal") -> SectionWrite:
        return SectionWrite("ai", self.name, self.values, self.request, self.target_file)


PROVIDERS = [
    ProviderSpec(
        "unitysvc",
        "UnitySVC",
        "recommended - one key for AI and email notifications",
        "UNITYSVC_API_KEY",
        "https://unitysvc.com",
    ),
    ProviderSpec("openai", "OpenAI", "", "OPENAI_API_KEY", "https://platform.openai.com/api-keys"),
    ProviderSpec(
        "anthropic",
        "Anthropic",
        "",
        "ANTHROPIC_API_KEY",
        "https://console.anthropic.com/settings/keys",
    ),
    ProviderSpec("ollama", "Ollama", "runs locally, no key", None, None),
]
PROVIDER_BY_KEY = {provider.key: provider for provider in PROVIDERS}
PROVIDER_LABELS = {
    **{provider.key: provider.label for provider in PROVIDERS},
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
}


def env_var_name(value: Any) -> str | None:
    match = _PLACEHOLDER.match(value) if isinstance(value, str) else None
    return match.group(1) if match else None


def scrub(text: str, secret: str | None) -> str:
    if secret:
        text = text.replace(secret, "<REDACTED>")
    return _SECRET_TOKEN.sub("<REDACTED>", text)


def _build_ai_config(name: str, raw: Dict[str, Any]) -> Tuple[AIConfig | None, str | None]:
    provider = str(raw.get("provider", name)).lower()
    backend = supported_ai_backends.get(provider)
    if backend is None:
        supported = ", ".join(sorted(supported_ai_backends))
        return None, f'Unknown provider "{provider}"; supported: {supported}'
    var = env_var_name(raw.get("api_key"))
    if var is not None and var not in os.environ:
        return None, f"Set the environment variable {var}"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return backend.get_config(name=name, **raw), None
    except Exception as e:
        return None, _MARKUP.sub("", str(e))


def load_ai_sections(files: List[Path]) -> List[AISection]:
    """Merge [ai.*] tables across config files and build enabled AI configs."""
    merged: Dict[str, Dict[str, Any]] = {}
    owners: Dict[str, List[Path]] = {}
    for path in files:
        for name, values in read_toml(path).get("ai", {}).items():
            merged[name] = merge_dicts(
                [copy.deepcopy(merged.get(name, {})), copy.deepcopy(values)]
            )
            owners.setdefault(name, []).append(path)
    sections = []
    for name, raw in merged.items():
        section = AISection(name=name, raw=raw, files=owners[name])
        if section.enabled:
            section.config, section.problem = _build_ai_config(name, raw)
        sections.append(section)
    return sections


async def run_in_daemon_thread(fn: Callable[..., T], *args: Any) -> T:
    """Run blocking ``fn`` in a daemon thread and await its result.

    Unlike ``asyncio.to_thread``, a daemon thread does not keep the interpreter alive, so
    Ctrl-C during a slow network probe exits at once instead of waiting for the timeout.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()

    def deliver(setter: Callable[[Any], None], value: Any) -> None:
        if not future.done():
            setter(value)

    def post(setter: Callable[[Any], None], value: Any) -> None:
        try:
            loop.call_soon_threadsafe(deliver, setter, value)
        except RuntimeError:  # the loop is closed: the user already left
            pass

    def run() -> None:
        try:
            result = fn(*args)
        except Exception as e:
            post(future.set_exception, e)
        else:
            post(future.set_result, result)

    threading.Thread(target=run, daemon=True).start()
    return await future


async def probe_sections(sections: List[AISection]) -> List[ProbeResult]:
    """Probe sections concurrently, in daemon threads; results are in input order."""
    return list(
        await asyncio.gather(
            *(run_in_daemon_thread(probe_ai_section, section) for section in sections)
        )
    )


def render_ai_section(proposal: AISectionProposal) -> str:
    return render_section(proposal.to_write())


async def commit_ai_section(
    ui: SetupUI, proposal: AISectionProposal, ctx: AISetupContext
) -> CommitOutcome:
    return await commit_section(ui, proposal.to_write(), ctx.files, ctx.backup_dir)


def model_matches(model: str, available: List[str]) -> bool:
    target = _normalize_model(model)
    return any(_normalize_model(candidate) == target for candidate in available)


def probe_ai_section(section: AISection, timeout: float = 15.0) -> ProbeResult:
    """Check one AI section by listing models and sending a one-token request."""
    backend_class = supported_ai_backends.get(section.provider)
    default_model = getattr(backend_class, "default_model", "")
    model = str(section.raw.get("model") or default_model)
    if section.config is None or backend_class is None:
        return ProbeResult(
            False, "config", model, section.problem or "Section could not be loaded"
        )

    backend = backend_class(config=section.config)
    # only a key the user configured is a secret; Ollama's placeholder default ("ollama")
    # would otherwise be scrubbed out of every error message that mentions Ollama
    secret = section.config.api_key if section.raw.get("api_key") else None
    client = _probe_client(backend, timeout)

    available: List[str] = []
    try:
        available = [model_info.id for model_info in client.models.list()]
    except _CONNECTION_ERRORS:
        return ProbeResult(False, "models", model, f"Can't reach {_base_url(backend)}")
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status in (401, 403):
            return ProbeResult(False, "models", model, f"Key rejected by {section.name}")
        if status not in (404, 405) and not isinstance(e, AttributeError):
            message = f"{section.name}: {scrub(str(e), secret)[:200]}"
            return ProbeResult(False, "models", model, message)
        available = []
    if available and not model_matches(model, available):
        shown = ", ".join(available[:10]) + (", ..." if len(available) > 10 else "")
        return ProbeResult(
            False,
            "models",
            model,
            f'Model "{model}" is not available; available: {shown}',
            available,
        )

    try:
        _ping(backend, client, model)
    except _CONNECTION_ERRORS:
        return ProbeResult(False, "request", model, f"Can't reach {_base_url(backend)}", available)
    except Exception as e:
        message = f"{section.name} request failed: {scrub(str(e), secret)[:200]}"
        return ProbeResult(False, "request", model, message, available)
    return ProbeResult(True, "request", model, f"{section.name} - {model}", available)


async def configure_ai(
    ui: SetupUI,
    config_files: List[Path],
    *,
    section_name: str | None = None,
    home: Path | None = None,
) -> int:
    """Run the interactive AI setup flow; return a process exit code."""
    home = home or amm_home
    default_file = config_files[-1] if config_files else home / "config.toml"
    ctx = AISetupContext(
        files=list(config_files),
        default_file=default_file,
        backup_dir=home / "backups",
    )
    try:
        await _check_existing_ai(ui, ctx)
        while True:
            proposal = await propose_ai_section(ui, ctx, section_name=section_name)
            if proposal is None:
                return 0
            outcome = await commit_ai_section(ui, proposal, ctx)
            if outcome is CommitOutcome.DECLINED:
                continue
            if outcome is CommitOutcome.FAILED:
                return 1
            retry = await _after_commit(ui, proposal, ctx)
            if not retry:
                return 0
    except SetupClosedError:
        return 0
    except (ConfigReadError, UnsupportedAISectionError) as e:
        await ui.say(str(e), kind="error")
        return 1


async def propose_ai_section(
    ui: SetupUI, ctx: AISetupContext, *, section_name: str | None = None
) -> AISectionProposal | None:
    """Ask for the details of one [ai.*] section and return the section to write.

    Which provider the section uses is decided before anything is asked:

    - an existing ``[ai.NAME]`` keeps its own provider;
    - a new section named after a provider (``ai.openai``) uses that provider;
    - only a new section with another name (``ai.work``), or plain ``ai``, asks which AI.

    Plain ``ai`` creates or updates the section named after the chosen provider. aimm-configure
    never writes a provider that contradicts a provider-named section; a mismatch made by hand
    (``[ai.openai]`` with ``provider = "anthropic"``) is kept and flagged, not converted.
    """
    sections = load_ai_sections(ctx.files)
    by_name = {section.name: section for section in sections}
    named = by_name.get(section_name) if section_name else None

    if named is not None:
        provider = named.provider
    elif section_name is not None and section_name.lower() in supported_ai_backends:
        provider = section_name.lower()
    else:
        options = [Choice(spec.key, spec.label, spec.hint) for spec in PROVIDERS]
        options.append(Choice("quit", "Quit"))
        provider = await ui.choose("Which AI do you want to configure?", options, "unitysvc")
        if provider == "quit":
            return None

    spec = PROVIDER_BY_KEY.get(provider)
    if spec is None:
        label = PROVIDER_LABELS.get(provider, provider)
        raise UnsupportedAISectionError(
            f"aimm-configure can set up UnitySVC, OpenAI, Anthropic and Ollama; "
            f"{label} sections have to be edited by hand."
        )

    name = section_name or provider
    target = by_name.get(name)
    if target is not None and target.provider != provider:
        if named is None:
            # plain `ai`: [ai.<provider>] exists but was set up by hand for another provider
            await ui.say(
                f"[ai.{name}] uses provider {target.provider!r}; leaving it unchanged.",
                kind="warning",
            )
            name = _new_name(provider, sections)
            target = None
    if named is not None and name.lower() in supported_ai_backends and provider != name.lower():
        await ui.say(
            f"[ai.{name}] is set to provider {provider!r}, which does not match its name. "
            f"It is updated as {provider!r}; consider renaming it.",
            kind="warning",
        )

    old = target.raw if target else {}
    values: Dict[str, Any] = {"provider": provider}
    if spec.env_var:
        var = env_var_name(old.get("api_key")) or spec.env_var
        values["api_key"] = f"${{{var}}}"
    if provider == "unitysvc":
        current = old.get("model")
        default_tier = current if current in UNITYSVC_TIERS else "balanced"
        tiers = [Choice(tier, tier) for tier in UNITYSVC_TIERS]
        values["model"] = await ui.choose("Which UnitySVC tier?", tiers, default_tier)
    elif provider == "ollama":
        values["base_url"] = await _ask_safe_text(
            ui, "Ollama URL", old.get("base_url") or OLLAMA_URL
        )
        values["model"] = await _ask_safe_text(
            ui, "Model", old.get("model") or OllamaBackend.default_model
        )
    else:
        backend = OpenAIBackend if provider == "openai" else AnthropicBackend
        values["model"] = await _ask_safe_text(
            ui, "Model", old.get("model") or backend.default_model
        )

    # shared settings: the section's own when updating, else from an existing AI section
    template = target or (sections[0] if sections else None)
    if template is not None:
        values.update({key: template.raw[key] for key in SHARED_AI_KEYS if key in template.raw})

    if name.lower() == provider:
        values.pop("provider")
    request = f"Use {spec.label} ({values['model']}) to rate marketplace listings."
    return AISectionProposal(
        name=name,
        values=values,
        request=request,
        target_file=target.files[-1] if target else ctx.default_file,
    )


async def _check_existing_ai(ui: SetupUI, ctx: AISetupContext) -> None:
    sections = load_ai_sections(ctx.files)
    enabled = [section for section in sections if section.enabled]
    if not enabled:
        return
    await ui.say(f"Checking {len(enabled)} AI service(s)...")
    results = await probe_sections(enabled)
    by_name = dict(zip([section.name for section in enabled], results))
    for section in sections:
        result = by_name.get(section.name)
        if result is None:
            await ui.say(f"- {section.name} - disabled")
        elif result.ok:
            await ui.say(f"OK {_label(section, result)}", kind="success")
        else:
            await ui.say(f"{section.name} - {result.message}", kind="warning")


async def _after_commit(ui: SetupUI, proposal: AISectionProposal, ctx: AISetupContext) -> bool:
    var = env_var_name(proposal.values.get("api_key"))
    if var is None or var in os.environ:
        section = next((s for s in load_ai_sections(ctx.files) if s.name == proposal.name), None)
        if section is None:
            await ui.say(
                f"[ai.{proposal.name}] was written but could not be found when the config "
                "was read back; check the file and run aimm-configure again.",
                kind="error",
            )
            return False
        [result] = await probe_sections([section])
        if result.ok:
            await ui.say(f"{section.name} works ({result.model}).", kind="success")
            return False
        await ui.say(result.message, kind="error")
        return True

    provider = str(proposal.values.get("provider", proposal.name))
    spec = PROVIDER_BY_KEY.get(provider)
    if spec and spec.key_url:
        await ui.say(f"Get a {spec.label} API key at {spec.key_url}.")
    await ui.say(
        f"Set it in your shell and add the line to your shell profile to keep it:\n\n"
        f"```bash\nexport {var}=<your key>\n```\n\n"
        "Then run `aimm-configure` again.",
        markdown=True,
    )
    return False


async def _ask_safe_text(ui: SetupUI, prompt: str, default: str) -> str:
    while True:
        answer = (await ui.ask_text(prompt, default)).strip()
        if _TYPED_KEY.match(answer):
            await ui.say(
                "That looks like an API key. Keys never go into aimm; set the key as an "
                "environment variable instead.",
                kind="warning",
            )
            continue
        return answer or default


def _new_name(provider: str, sections: List[AISection]) -> str:
    names = {section.name for section in sections}
    name, suffix = provider, 1
    while name in names:
        suffix += 1
        name = f"{provider}_{suffix}"
    return name


def _label(section: AISection, result: ProbeResult) -> str:
    provider = PROVIDER_LABELS.get(section.provider, section.provider)
    return f"{section.name} - {provider}, {result.model}"


def _normalize_model(model: str) -> str:
    return model.removeprefix("models/").removesuffix(":latest")


def _probe_client(backend: AIBackend, timeout: float) -> Any:
    backend.connect()
    return backend.client.with_options(timeout=timeout, max_retries=0)


def _base_url(backend: AIBackend) -> str:
    return (
        getattr(backend.config, "base_url", None)
        or getattr(backend, "base_url", None)
        or "the provider API"
    )


def _ping(backend: AIBackend, client: Any, model: str) -> None:
    if isinstance(backend, AnthropicBackend):
        client.messages.create(model=model, max_tokens=1, messages=_PING)
        return
    try:
        client.chat.completions.create(model=model, messages=_PING, max_tokens=1)
    except Exception as e:
        if "max_completion_tokens" not in str(e):
            raise
        client.chat.completions.create(model=model, messages=_PING, max_completion_tokens=1)
