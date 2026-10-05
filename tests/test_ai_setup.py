from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List

import httpx
import openai
import pytest

from ai_marketplace_monitor import ai_setup
from ai_marketplace_monitor.ai import UnitySVCConfig
from ai_marketplace_monitor.ai_setup import (
    AISection,
    AISectionProposal,
    AISetupContext,
    CommitOutcome,
    ConfigReadError,
    JsonSetupUI,
    ProbeResult,
    ScriptedSetupUI,
    commit_ai_section,
    configure_ai,
    env_var_name,
    load_ai_sections,
    model_matches,
    probe_ai_section,
    propose_ai_section,
    render_ai_section,
    scrub,
)

REQUEST = httpx.Request("GET", "https://api.svcpass.com/p/llm/models")
VALUES = {"api_key": "${UNITYSVC_API_KEY}", "model": "balanced"}

EXISTING = """\
# my config
[marketplace.facebook]
search_city = "houston"  # home

[ai.unitysvc]
request = "keep me"
api_key = "${OLD_KEY}"
model = "fast"

[item.bike]
search_phrases = "bike"
"""


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
        return iter(SimpleNamespace(id=model) for model in self._models)

    def _create(self: "FakeClient", **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        if self._create_errors:
            raise self._create_errors.pop(0)
        return SimpleNamespace(choices=[])


def write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def context(tmp_path: Path, files: List[Path] | None = None) -> AISetupContext:
    return AISetupContext(
        files=list(files or []),
        default_file=tmp_path / "home" / "config.toml",
        backup_dir=tmp_path / "backups",
    )


def proposal(target: Path, name: str = "unitysvc") -> AISectionProposal:
    return AISectionProposal(name, dict(VALUES), "Use UnitySVC.", target)


def status_error(code: int, message: str = "boom") -> openai.APIStatusError:
    return openai.APIStatusError(
        message, response=httpx.Response(code, request=REQUEST), body=None
    )


def section(model: str | None = None, problem: str | None = None) -> AISection:
    raw = {"api_key": "svcpass_secretvalue123"} | ({"model": model} if model else {})
    config = None if problem else UnitySVCConfig(name="unitysvc", **raw)
    return AISection("unitysvc", raw, [], config=config, problem=problem)


def use_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr(ai_setup, "_probe_client", lambda backend, timeout: client)


def test_env_var_name() -> None:
    assert env_var_name("${UNITYSVC_API_KEY}") == "UNITYSVC_API_KEY"
    assert env_var_name("svcpass_x") is None
    assert env_var_name(None) is None


async def test_json_setup_ui_uses_serializable_prompt_messages() -> None:
    sent: List[Dict[str, Any]] = []
    answers = iter(
        [
            {"type": "answer", "value": "openai"},
            {"type": "answer", "value": ""},
            {"type": "answer", "value": True},
        ]
    )

    async def send(message: Dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> Dict[str, Any]:
        return next(answers)

    ui = JsonSetupUI(send, receive)

    await ui.say("Checking AI", kind="warning", markdown=True)
    choice = await ui.choose("Provider?", [ai_setup.Choice("openai", "OpenAI")])
    model = await ui.ask_text("Model", "gpt-5")
    confirmed = await ui.confirm("Write?")

    assert choice == "openai"
    assert model == "gpt-5"
    assert confirmed
    assert sent == [
        {
            "type": "message",
            "kind": "warning",
            "text": "Checking AI",
            "markdown": True,
        },
        {
            "type": "prompt",
            "prompt_type": "choice",
            "prompt": "Provider?",
            "options": [{"value": "openai", "label": "OpenAI", "hint": ""}],
            "default": None,
        },
        {
            "type": "prompt",
            "prompt_type": "text",
            "prompt": "Model",
            "default": "gpt-5",
        },
        {
            "type": "prompt",
            "prompt_type": "confirm",
            "prompt": "Write?",
            "default": True,
        },
    ]


def test_load_ai_sections_merges_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    first = write(tmp_path / "a.toml", '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n')
    second = write(
        tmp_path / "b.toml",
        '[ai.unitysvc]\nmodel = "fast"\n[ai.other]\nprovider = "openai"\napi_key = "k"\n',
    )

    sections = load_ai_sections([first, second])

    assert [section.name for section in sections] == ["unitysvc", "other"]
    assert sections[0].raw == {"api_key": "${UNITYSVC_API_KEY}", "model": "fast"}
    assert sections[0].files == [first, second]
    assert isinstance(sections[0].config, UnitySVCConfig)
    assert sections[1].provider == "openai"


def test_unset_env_var_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    path = write(tmp_path / "config.toml", '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n')

    [section] = load_ai_sections([path])

    assert section.config is None
    assert section.problem == "Set the environment variable UNITYSVC_API_KEY"


def test_unknown_provider(tmp_path: Path) -> None:
    [section] = load_ai_sections([write(tmp_path / "config.toml", '[ai.x]\nprovider = "foo"\n')])
    assert section.problem == (
        'Unknown provider "foo"; supported: anthropic, deepseek, gemini, ollama, openai, unitysvc'
    )


def test_disabled_section_not_built(tmp_path: Path) -> None:
    [section] = load_ai_sections(
        [write(tmp_path / "config.toml", '[ai.unitysvc]\nenabled = false\napi_key = "k"\n')]
    )
    assert not section.enabled
    assert section.config is None and section.problem is None


def test_unparsable_file(tmp_path: Path) -> None:
    path = write(tmp_path / "bad.toml", "[ai\n")
    with pytest.raises(ConfigReadError) as info:
        load_ai_sections([path])
    assert info.value.path == path


async def test_propose_unitysvc_new_section(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    proposal = await propose_ai_section(ScriptedSetupUI(["unitysvc", "balanced"]), ctx)

    assert proposal is not None
    assert proposal.name == "unitysvc"
    assert proposal.values == {"api_key": "${UNITYSVC_API_KEY}", "model": "balanced"}
    assert proposal.target_file == ctx.default_file
    assert proposal.request == "Use UnitySVC (balanced) to rate marketplace listings."


async def test_propose_existing_section_keeps_env_var_and_shared_fields(tmp_path: Path) -> None:
    path = write(
        tmp_path / "config.toml",
        '[ai.mine]\nprovider = "unitysvc"\napi_key = "${MY_KEY}"\n'
        'model = "fast"\ntimeout = 5\n',
    )
    proposal = await propose_ai_section(
        ScriptedSetupUI(["unitysvc", "premium"]), context(tmp_path, [path])
    )

    assert proposal is not None
    assert proposal.name == "mine"
    assert proposal.values == {
        "provider": "unitysvc",
        "api_key": "${MY_KEY}",
        "model": "premium",
        "timeout": 5,
    }
    assert proposal.target_file == path


async def test_propose_named_provider_defaults_to_matching_provider(tmp_path: Path) -> None:
    proposal = await propose_ai_section(
        ScriptedSetupUI(["", ""]), context(tmp_path), section_name="openai"
    )

    assert proposal is not None
    assert proposal.name == "openai"
    assert proposal.values["api_key"] == "${OPENAI_API_KEY}"
    assert "provider" not in proposal.values


async def test_propose_refuses_key_like_input(tmp_path: Path) -> None:
    ui = ScriptedSetupUI(["openai", "sk-abcdefghijklmnop", "gpt-5"])

    proposal = await propose_ai_section(ui, context(tmp_path))

    assert proposal is not None
    assert proposal.values["model"] == "gpt-5"
    [warning] = ui.said("warning")
    assert "sk-abcdefghijklmnop" not in warning and "environment variable" in warning


async def test_propose_quit(tmp_path: Path) -> None:
    assert await propose_ai_section(ScriptedSetupUI(["quit"]), context(tmp_path)) is None


def test_render_ai_section() -> None:
    assert render_ai_section(proposal(Path("x.toml"))) == (
        '[ai.unitysvc]\nrequest = "Use UnitySVC."\napi_key = "${UNITYSVC_API_KEY}"\n'
        'model = "balanced"\n'
    )


async def test_commit_decline_writes_nothing(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    ui = ScriptedSetupUI(["no"])

    assert await commit_ai_section(ui, proposal(ctx.default_file), ctx) is CommitOutcome.DECLINED
    assert not ctx.default_file.exists()
    assert "```toml" in ui.said()[0]


async def test_commit_new_default_file_created(tmp_path: Path) -> None:
    ctx = context(tmp_path)

    outcome = await commit_ai_section(ScriptedSetupUI(["yes"]), proposal(ctx.default_file), ctx)

    assert outcome is CommitOutcome.WRITTEN
    assert ctx.default_file.read_text() == render_ai_section(proposal(ctx.default_file))
    assert ctx.files == [ctx.default_file]
    assert not (tmp_path / "backups").exists()


async def test_commit_update_preserves_file_and_creates_private_backup(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", EXISTING)
    ctx = context(tmp_path, [path])

    assert (
        await commit_ai_section(ScriptedSetupUI(["yes"]), proposal(path), ctx)
        is CommitOutcome.WRITTEN
    )

    text = path.read_text()
    assert text.startswith('# my config\n[marketplace.facebook]\nsearch_city = "houston"  # home')
    assert 'request = "Use UnitySVC."\napi_key = "${UNITYSVC_API_KEY}"' in text
    assert "OLD_KEY" not in text and "[item.bike]" in text
    [backup] = list((tmp_path / "backups").iterdir())
    assert backup.name.startswith("config.toml.")
    assert backup.read_text() == EXISTING
    assert backup.stat().st_mode & 0o777 == 0o600


async def test_commit_later_file_conflict_detected(tmp_path: Path) -> None:
    first = write(tmp_path / "config.toml", "")
    later = write(tmp_path / "later.toml", '[ai.unitysvc]\nmodel = "fast"\n')
    ctx = context(tmp_path, [first, later])
    ui = ScriptedSetupUI(["yes"])

    assert await commit_ai_section(ui, proposal(first), ctx) is CommitOutcome.FAILED

    [error] = ui.said("error")
    assert str(later) in error and "model" in error


def test_probe_config_problem_skips_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(backend: Any, timeout: float) -> Any:
        raise AssertionError("no network expected")

    monkeypatch.setattr(ai_setup, "_probe_client", fail)
    result = probe_ai_section(section(problem="Set the environment variable UNITYSVC_API_KEY"))
    assert (result.ok, result.step) == (False, "config")
    assert result.message == "Set the environment variable UNITYSVC_API_KEY"


def test_probe_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    use_client(monkeypatch, client)

    result = probe_ai_section(section())

    assert result.ok and result.available == ["fast", "balanced"]
    assert client.create_calls[0]["max_tokens"] == 1
    assert client.create_calls[0]["model"] == "balanced"


def test_probe_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    use_client(monkeypatch, FakeClient(list_error=status_error(401)))
    assert probe_ai_section(section()).message == "Key rejected by unitysvc"


def test_probe_model_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    use_client(monkeypatch, FakeClient(models=[f"m{i}" for i in range(12)]))
    result = probe_ai_section(section(model="nope"))
    assert not result.ok and result.step == "models"
    assert result.message.startswith('Model "nope" is not available; available: m0, m1')
    assert result.message.endswith(", ...")


def test_probe_request_error_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    error = status_error(401, "no credit for svcpass_secretvalue123 / sk-abcdefghijk")
    use_client(monkeypatch, FakeClient(create_errors=[error]))

    result = probe_ai_section(section())

    assert (result.ok, result.step) == (False, "request")
    assert "svcpass_secretvalue123" not in result.message
    assert "sk-abcdefghijk" not in result.message


def test_probe_retries_with_max_completion_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(
        create_errors=[status_error(400, "Use 'max_completion_tokens' instead of max_tokens")]
    )
    use_client(monkeypatch, client)

    assert probe_ai_section(section()).ok
    assert client.create_calls[1]["max_completion_tokens"] == 1


def test_model_matching_and_scrub() -> None:
    assert model_matches("gemini-2.5-flash", ["models/gemini-2.5-flash"])
    assert model_matches("llama3", ["llama3:latest"])
    assert not model_matches("llama3", ["llama3.1:latest"])
    assert scrub("key abc123 leaked", "abc123") == "key <REDACTED> leaked"
    assert scrub("token sk-ant-abcdefgh", None) == "token <REDACTED>"


async def test_configure_ai_writes_section_and_prints_env_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    ui = ScriptedSetupUI(["unitysvc", "balanced", "yes"])

    assert await configure_ai(ui, [], home=tmp_path / "home") == 0

    written = (tmp_path / "home" / "config.toml").read_text()
    assert (
        '[ai.unitysvc]\nrequest = "Use UnitySVC (balanced) to rate marketplace listings."'
        in written
    )
    assert 'api_key = "${UNITYSVC_API_KEY}"' in written
    assert any("export UNITYSVC_API_KEY=<your key>" in text for text in ui.said())


async def test_configure_ai_writes_new_section_to_supplied_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    config = write(tmp_path / "custom.toml", "")
    ui = ScriptedSetupUI(["unitysvc", "balanced", "yes"])

    assert await configure_ai(ui, [config], home=tmp_path / "home") == 0

    assert "[ai.unitysvc]" in config.read_text()
    assert not (tmp_path / "home" / "config.toml").exists()


async def test_configure_ai_probes_after_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    monkeypatch.setattr(
        ai_setup,
        "probe_ai_section",
        lambda section: ProbeResult(True, "request", "balanced", "ok"),
    )
    ui = ScriptedSetupUI(["unitysvc", "balanced", "yes"])

    assert await configure_ai(ui, [], home=tmp_path / "home") == 0

    assert any("unitysvc works (balanced)." in text for text in ui.said("success"))
