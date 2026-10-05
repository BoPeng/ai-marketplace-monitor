"""Interactive setup for [ai.*] config sections."""

from __future__ import annotations

import asyncio
import copy
import os
import re
import shutil
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, ClassVar, Dict, List, Protocol, Tuple

import anthropic
import openai
import tomlkit
from rich.console import Console
from rich.markdown import Markdown
from tomlkit.exceptions import ParseError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .ai import AIBackend, AIConfig, AnthropicBackend, OllamaBackend, OpenAIBackend
from .config import supported_ai_backends
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


class ConfigReadError(Exception):
    """A config file could not be read or parsed."""

    def __init__(self: "ConfigReadError", path: Path, message: str) -> None:
        super().__init__(f"Cannot read {path}: {message}")
        self.path = path


class SetupClosedError(Exception):
    """The user left the setup flow."""


class CommitOutcome(Enum):
    WRITTEN = "written"
    DECLINED = "declined"
    FAILED = "failed"


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    hint: str = ""

    def to_json(self: "Choice") -> Dict[str, str]:
        return {"value": self.value, "label": self.label, "hint": self.hint}


class SetupUI(Protocol):
    async def say(
        self: "SetupUI", text: str, *, kind: str = "info", markdown: bool = False
    ) -> None: ...

    async def choose(
        self: "SetupUI", prompt: str, options: List[Choice], default: str | None = None
    ) -> str: ...

    async def ask_text(self: "SetupUI", prompt: str, default: str | None = None) -> str: ...

    async def confirm(self: "SetupUI", prompt: str, default: bool = True) -> bool: ...


class JsonSetupUI:
    """JSON message adapter for WebSocket or other remote front ends."""

    def __init__(
        self: "JsonSetupUI",
        send: Callable[[Dict[str, Any]], Awaitable[None]],
        receive: Callable[[], Awaitable[Dict[str, Any]]],
    ) -> None:
        self._send = send
        self._receive = receive

    async def say(
        self: "JsonSetupUI", text: str, *, kind: str = "info", markdown: bool = False
    ) -> None:
        await self._send({"type": "message", "kind": kind, "text": text, "markdown": markdown})

    async def choose(
        self: "JsonSetupUI", prompt: str, options: List[Choice], default: str | None = None
    ) -> str:
        await self._send(
            {
                "type": "prompt",
                "prompt_type": "choice",
                "prompt": prompt,
                "options": [option.to_json() for option in options],
                "default": default,
            }
        )
        answer = await self._answer()
        if answer in (None, "") and default is not None:
            return default
        if not isinstance(answer, str):
            raise ValueError("Choice answers must be strings.")
        allowed = {option.value for option in options}
        if answer not in allowed:
            raise ValueError(f"{answer!r} is not one of {sorted(allowed)}")
        return answer

    async def ask_text(self: "JsonSetupUI", prompt: str, default: str | None = None) -> str:
        await self._send(
            {
                "type": "prompt",
                "prompt_type": "text",
                "prompt": prompt,
                "default": default,
            }
        )
        answer = await self._answer()
        if answer in (None, "") and default is not None:
            return default
        if not isinstance(answer, str):
            raise ValueError("Text answers must be strings.")
        return answer

    async def confirm(self: "JsonSetupUI", prompt: str, default: bool = True) -> bool:
        await self._send(
            {
                "type": "prompt",
                "prompt_type": "confirm",
                "prompt": prompt,
                "default": default,
            }
        )
        answer = await self._answer()
        if answer in (None, ""):
            return default
        if isinstance(answer, bool):
            return answer
        if isinstance(answer, str) and answer.lower() in ("y", "yes", "true"):
            return True
        if isinstance(answer, str) and answer.lower() in ("n", "no", "false"):
            return False
        raise ValueError("Confirm answers must be booleans or yes/no strings.")

    async def _answer(self: "JsonSetupUI") -> Any:
        message = await self._receive()
        message_type = message.get("type")
        if message_type in ("cancel", "close"):
            raise SetupClosedError
        if message_type != "answer":
            raise ValueError(f"Expected answer message, got {message_type!r}.")
        return message.get("value")


class ConsoleSetupUI:
    """Terminal front end for AI setup."""

    _styles: ClassVar[Dict[str, str]] = {
        "info": "",
        "success": "green",
        "warning": "yellow",
        "error": "bold red",
    }

    def __init__(
        self: "ConsoleSetupUI",
        console: Console | None = None,
        read: Callable[[str], str] = input,
        interactive: bool | None = None,
    ) -> None:
        if interactive is None:
            interactive = sys.stdin.isatty()
        if not interactive:
            raise RuntimeError("aimm-configure needs an interactive terminal")
        self.console = console or Console()
        self._read = read

    async def say(
        self: "ConsoleSetupUI", text: str, *, kind: str = "info", markdown: bool = False
    ) -> None:
        if markdown:
            self.console.print(Markdown(text))
            return
        self.console.print(text, style=self._styles.get(kind, ""), markup=False, highlight=False)

    async def choose(
        self: "ConsoleSetupUI", prompt: str, options: List[Choice], default: str | None = None
    ) -> str:
        self.console.print(prompt, markup=False, highlight=False)
        for index, option in enumerate(options, 1):
            hint = f" - {option.hint}" if option.hint else ""
            suffix = " (default)" if option.value == default else ""
            self.console.print(
                f"  {index}) {option.label}{hint}{suffix}", markup=False, highlight=False
            )
        while True:
            raw = self._input("> ").strip()
            if not raw and default is not None:
                return default
            if raw.isdecimal() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1].value
            self.console.print(f"Please enter a number from 1 to {len(options)}.", style="yellow")

    async def ask_text(self: "ConsoleSetupUI", prompt: str, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        raw = self._input(f"{prompt}{suffix}: ")
        if not raw.strip() and default is not None:
            return default
        return raw

    async def confirm(self: "ConsoleSetupUI", prompt: str, default: bool = True) -> bool:
        suffix = " [Y/n] " if default else " [y/N] "
        while True:
            raw = self._input(prompt + suffix).strip().lower()
            if not raw:
                return default
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no"):
                return False
            self.console.print("Please answer y or n.", style="yellow")

    def _input(self: "ConsoleSetupUI", prompt: str) -> str:
        try:
            return self._read(prompt)
        except (KeyboardInterrupt, EOFError) as e:
            raise SetupClosedError from e


class ScriptedSetupUI:
    """Test front end with canned answers."""

    def __init__(self: "ScriptedSetupUI", answers: List[str]) -> None:
        self.answers = list(answers)
        self.messages: List[Tuple[str, str]] = []
        self.questions: List[str] = []

    async def say(
        self: "ScriptedSetupUI", text: str, *, kind: str = "info", markdown: bool = False
    ) -> None:
        self.messages.append((kind, text))

    async def choose(
        self: "ScriptedSetupUI", prompt: str, options: List[Choice], default: str | None = None
    ) -> str:
        answer = self._answer(prompt)
        if not answer and default is not None:
            return default
        allowed = {option.value for option in options}
        if answer not in allowed:
            raise AssertionError(f"{answer!r} is not one of {sorted(allowed)}")
        return answer

    async def ask_text(self: "ScriptedSetupUI", prompt: str, default: str | None = None) -> str:
        answer = self._answer(prompt)
        return default if not answer and default is not None else answer

    async def confirm(self: "ScriptedSetupUI", prompt: str, default: bool = True) -> bool:
        answer = self._answer(prompt)
        if not answer:
            return default
        if answer not in ("yes", "no"):
            raise AssertionError(f"Confirm answers must be yes or no, got {answer!r}")
        return answer == "yes"

    def said(self: "ScriptedSetupUI", kind: str | None = None) -> List[str]:
        return [text for message_kind, text in self.messages if kind in (None, message_kind)]

    def _answer(self: "ScriptedSetupUI", prompt: str) -> str:
        self.questions.append(prompt)
        if not self.answers:
            raise AssertionError(f"unexpected question: {prompt}")
        answer = self.answers.pop(0)
        if answer == "<close>":
            raise SetupClosedError
        return answer


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


def resolve_setup_config_files(config_files: List[Path] | None) -> List[Path]:
    """Config files in read order: default config if present, then each explicit file."""
    explicit = []
    for file_path in config_files or []:
        expanded = file_path.expanduser().resolve()
        if not expanded.exists():
            raise FileNotFoundError(f"Config file {expanded} not found.")
        explicit.append(expanded)
    default_config = amm_home / "config.toml"
    return ([default_config] if default_config.exists() else []) + explicit


def read_toml(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "rb") as file:
            return tomllib.load(file)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigReadError(path, str(e)) from e


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
    secret = section.config.api_key
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


def render_ai_section(proposal: AISectionProposal) -> str:
    values = (
        {"request": proposal.request, **proposal.values} if proposal.request else proposal.values
    )
    return tomlkit.dumps({"ai": {proposal.name: values}})


def backup_file(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{path.name}.{datetime.now():%Y%m%d-%H%M%S}"
    dest = backup_dir / stem
    counter = 1
    while dest.exists():
        counter += 1
        dest = backup_dir / f"{stem}-{counter}"
    shutil.copy2(path, dest)
    os.chmod(dest, 0o600)
    return dest


def write_ai_section(path: Path, proposal: AISectionProposal) -> None:
    """Add or replace one [ai.*] section, preserving the rest of the file."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    doc = tomlkit.parse(text) if text else tomlkit.document()
    if "ai" not in doc:
        doc["ai"] = tomlkit.table(is_super_table=True)
    parent: Any = doc["ai"]
    old = parent.get(proposal.name)
    table = tomlkit.table()
    if proposal.request:
        table["request"] = proposal.request
    elif old is not None and "request" in old:
        table["request"] = old["request"]
    for key, value in proposal.values.items():
        table[key] = value
    parent[proposal.name] = table
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


async def commit_ai_section(
    ui: SetupUI, proposal: AISectionProposal, ctx: AISetupContext
) -> CommitOutcome:
    await ui.say(f"```toml\n{render_ai_section(proposal)}```", markdown=True)
    if not await ui.confirm(f"Write this to {proposal.target_file}?"):
        return CommitOutcome.DECLINED
    try:
        if proposal.target_file.exists():
            backup_file(proposal.target_file, ctx.backup_dir)
        write_ai_section(proposal.target_file, proposal)
        if proposal.target_file not in ctx.files:
            ctx.files.insert(0, proposal.target_file)
        conflicts = _conflicts(ctx.files, proposal)
    except (ParseError, OSError, ConfigReadError) as e:
        await ui.say(f"Could not update {proposal.target_file}: {e}", kind="error")
        return CommitOutcome.FAILED

    if not conflicts:
        await ui.say(f"Saved [ai.{proposal.name}] to {proposal.target_file}.", kind="success")
        return CommitOutcome.WRITTEN
    detail = "; ".join(f"{other} ({', '.join(keys)})" for other, keys in conflicts)
    await ui.say(
        f"Saved to {proposal.target_file}, but [ai.{proposal.name}] is also set in "
        f"{detail}, which overrides or adds to it. Remove those keys there for this "
        "change to take effect.",
        kind="error",
    )
    return CommitOutcome.FAILED


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
    except (ConfigReadError, SetupClosedError) as e:
        if isinstance(e, ConfigReadError):
            await ui.say(str(e), kind="error")
            return 1
        return 0


async def propose_ai_section(
    ui: SetupUI, ctx: AISetupContext, *, section_name: str | None = None
) -> AISectionProposal | None:
    sections = load_ai_sections(ctx.files)
    named = next((section for section in sections if section.name == section_name), None)
    default = "unitysvc"
    if section_name in PROVIDER_BY_KEY:
        default = section_name
    if named and named.provider in PROVIDER_BY_KEY:
        default = named.provider
    options = [Choice(provider.key, provider.label, provider.hint) for provider in PROVIDERS]
    options.append(Choice("quit", "Quit"))
    choice = await ui.choose("Which AI do you want to configure?", options, default)
    if choice == "quit":
        return None

    spec = PROVIDER_BY_KEY[choice]
    if section_name:
        target = named
    else:
        target = next((section for section in sections if section.provider == choice), None)
    old = target.raw if target else {}

    values: Dict[str, Any] = {"provider": choice}
    if spec.env_var:
        var = env_var_name(old.get("api_key")) or spec.env_var
        values["api_key"] = f"${{{var}}}"
    if choice == "unitysvc":
        current = old.get("model")
        default_tier = current if current in UNITYSVC_TIERS else "balanced"
        tiers = [Choice(tier, tier) for tier in UNITYSVC_TIERS]
        values["model"] = await ui.choose("Which UnitySVC tier?", tiers, default_tier)
    elif choice == "ollama":
        values["base_url"] = await _ask_safe_text(
            ui, "Ollama URL", old.get("base_url") or OLLAMA_URL
        )
        values["model"] = await _ask_safe_text(
            ui, "Model", old.get("model") or OllamaBackend.default_model
        )
    else:
        backend = OpenAIBackend if choice == "openai" else AnthropicBackend
        values["model"] = await _ask_safe_text(
            ui, "Model", old.get("model") or backend.default_model
        )

    template = target or (sections[0] if sections else None)
    if template is not None:
        values.update({key: template.raw[key] for key in SHARED_AI_KEYS if key in template.raw})

    name = section_name or (target.name if target else _new_name(choice, sections))
    if name == choice:
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
    results = await asyncio.gather(
        *(asyncio.to_thread(probe_ai_section, section) for section in enabled)
    )
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
        section = next(
            section for section in load_ai_sections(ctx.files) if section.name == proposal.name
        )
        result = await asyncio.to_thread(probe_ai_section, section)
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


def _effective_ai_section(files: List[Path], name: str) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for path in files:
        merged.update(read_toml(path).get("ai", {}).get(name, {}))
    return merged


def _conflicts(files: List[Path], proposal: AISectionProposal) -> List[Tuple[Path, List[str]]]:
    effective = _effective_ai_section(files, proposal.name)
    wanted = proposal.values
    bad = {
        key
        for key, value in effective.items()
        if key != "request" and (key not in wanted or wanted[key] != value)
    }
    by_file: Dict[Path, List[str]] = {}
    for key in sorted(bad):
        owner = [
            path for path in files if key in read_toml(path).get("ai", {}).get(proposal.name, {})
        ][-1]
        by_file.setdefault(owner, []).append(key)
    return [(path, by_file[path]) for path in files if path in by_file]


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
