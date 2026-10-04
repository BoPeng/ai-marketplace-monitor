from types import SimpleNamespace
from typing import Any, Iterator, List

import httpx
import openai
import pytest

from ai_marketplace_monitor.ai import UnitySVCConfig
from ai_marketplace_monitor.chat import probe as probe_module
from ai_marketplace_monitor.chat.ai_sections import AISection
from ai_marketplace_monitor.chat.probe import model_matches, probe, scrub

REQUEST = httpx.Request("GET", "https://api.svcpass.com/p/llm/models")


def status_error(code: int, message: str = "boom") -> openai.APIStatusError:
    return openai.APIStatusError(
        message, response=httpx.Response(code, request=REQUEST), body=None
    )


class FakeClient:
    def __init__(
        self: "FakeClient",
        models: List[str] | None = None,
        list_error: Exception | None = None,
        create_errors: List[Exception] | None = None,
    ) -> None:
        self._models = models if models is not None else ["fast", "balanced"]
        self._list_error = list_error
        self._create_errors = list(create_errors or [])
        self.create_calls: List[dict] = []
        self.models = SimpleNamespace(list=self._list)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _list(self: "FakeClient") -> Iterator[Any]:
        if self._list_error:
            raise self._list_error
        return iter(SimpleNamespace(id=m) for m in self._models)

    def _create(self: "FakeClient", **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        if self._create_errors:
            raise self._create_errors.pop(0)
        return SimpleNamespace(choices=[])


def section(model: str | None = None, problem: str | None = None) -> AISection:
    raw = {"api_key": "svcpass_secretvalue123"} | ({"model": model} if model else {})
    config = None if problem else UnitySVCConfig(name="unitysvc", **raw)
    return AISection("unitysvc", raw, [], config=config, problem=problem)


def use(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr(probe_module, "_client", lambda backend, timeout: client)


def test_config_problem_skips_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(backend: Any, timeout: float) -> Any:
        raise AssertionError("no network expected")

    monkeypatch.setattr(probe_module, "_client", fail)
    result = probe(section(problem="Set the environment variable UNITYSVC_API_KEY"))
    assert (result.ok, result.step) == (False, "config")
    assert result.model == "balanced"
    assert result.message == "Set the environment variable UNITYSVC_API_KEY"


def test_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    use(monkeypatch, client)
    result = probe(section())
    assert result.ok and result.available == ["fast", "balanced"]
    assert client.create_calls[0]["max_tokens"] == 1
    assert client.create_calls[0]["model"] == "balanced"


def test_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeClient(list_error=status_error(401)))
    result = probe(section())
    assert (result.ok, result.step, result.message) == (
        False,
        "models",
        "Key rejected by unitysvc",
    )


def test_cannot_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeClient(list_error=openai.APIConnectionError(request=REQUEST)))
    result = probe(section())
    assert result.message == "Can't reach https://api.svcpass.com/p/llm"


def test_model_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeClient(models=[f"m{i}" for i in range(12)]))
    result = probe(section(model="nope"))
    assert not result.ok and result.step == "models"
    assert result.message.startswith('Model "nope" isn\'t available; available: m0, m1')
    assert result.message.endswith(", …")


def test_listing_unsupported_goes_to_request(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeClient(list_error=status_error(404)))
    assert probe(section()).ok


def test_request_error_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    error = status_error(401, "no credit for svcpass_secretvalue123 / sk-abcdefghijk")
    use(monkeypatch, FakeClient(create_errors=[error]))
    result = probe(section())
    assert (result.ok, result.step) == (False, "request")
    assert "svcpass_secretvalue123" not in result.message
    assert "sk-abcdefghijk" not in result.message
    assert result.message.startswith("unitysvc request failed:")


def test_retries_with_max_completion_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(
        create_errors=[status_error(400, "Use 'max_completion_tokens' instead of max_tokens")]
    )
    use(monkeypatch, client)
    assert probe(section()).ok
    assert client.create_calls[1]["max_completion_tokens"] == 1


def test_model_matching() -> None:
    assert model_matches("gemini-2.5-flash", ["models/gemini-2.5-flash"])
    assert model_matches("llama3", ["llama3:latest"])
    assert not model_matches("llama3", ["llama3.1:latest"])


def test_scrub() -> None:
    assert scrub("key abc123 leaked", "abc123") == "key <REDACTED> leaked"
    assert scrub("token sk-ant-abcdefgh", None) == "token <REDACTED>"
