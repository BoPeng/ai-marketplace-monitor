"""Two-step check that an AI section is usable: list models, then a 1-token request."""

import re
from dataclasses import dataclass, field
from typing import Any, List

import anthropic
import openai

from ..ai import AIBackend, AnthropicBackend
from ..config import supported_ai_backends
from .ai_sections import AISection

_TOKEN = re.compile(r"(svcpass_|sk-ant-|sk-)[A-Za-z0-9_\-]{4,}")
_PING = [{"role": "user", "content": "ping"}]
_CONNECTION_ERRORS = (openai.APIConnectionError, anthropic.APIConnectionError)


@dataclass
class ProbeResult:
    ok: bool
    step: str  # "config" | "models" | "request"
    model: str
    message: str
    available: List[str] = field(default_factory=list)


def scrub(text: str, secret: str | None) -> str:
    """Remove a known secret and anything that looks like an API key."""
    if secret:
        text = text.replace(secret, "<REDACTED>")
    return _TOKEN.sub("<REDACTED>", text)


def looks_like_secret(text: str) -> bool:
    """True when the text contains something shaped like an API key."""
    return _TOKEN.search(text) is not None


def _normalize(model: str) -> str:
    return model.removeprefix("models/").removesuffix(":latest")


def model_matches(model: str, available: List[str]) -> bool:
    target = _normalize(model)
    return any(_normalize(m) == target for m in available)


def _client(backend: AIBackend, timeout: float) -> Any:
    backend.connect()
    return backend.client.with_options(timeout=timeout, max_retries=0)


def _base_url(backend: AIBackend) -> str:
    return (
        getattr(backend.config, "base_url", None)
        or getattr(backend, "base_url", None)
        or "the provider's API"
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


def probe(section: AISection, timeout: float = 15.0) -> ProbeResult:
    backend_class = supported_ai_backends.get(section.provider)
    default_model = getattr(backend_class, "default_model", "")
    model = str(section.raw.get("model") or default_model)
    if section.config is None or backend_class is None:
        return ProbeResult(
            False, "config", model, section.problem or "Section could not be loaded"
        )

    backend = backend_class(config=section.config)
    secret = section.config.api_key
    name = section.name
    client = _client(backend, timeout)

    available: List[str] = []
    try:
        available = [m.id for m in client.models.list()]
    except _CONNECTION_ERRORS:
        return ProbeResult(False, "models", model, f"Can't reach {_base_url(backend)}")
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status in (401, 403):
            return ProbeResult(False, "models", model, f"Key rejected by {name}")
        if status not in (404, 405) and not isinstance(e, AttributeError):
            message = f"{name}: {scrub(str(e), secret)[:200]}"
            return ProbeResult(False, "models", model, message)
        available = []
    if available and not model_matches(model, available):
        shown = ", ".join(available[:10]) + (", …" if len(available) > 10 else "")
        message = f'Model "{model}" isn\'t available; available: {shown}'
        return ProbeResult(False, "models", model, message, available)

    try:
        _ping(backend, client, model)
    except _CONNECTION_ERRORS:
        return ProbeResult(False, "request", model, f"Can't reach {_base_url(backend)}", available)
    except Exception as e:
        message = f"{name} request failed: {scrub(str(e), secret)[:200]}"
        return ProbeResult(False, "request", model, message, available)
    return ProbeResult(True, "request", model, f"{name} — {model}", available)
