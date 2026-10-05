from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List

import httpx
import openai
import pytest

from ai_marketplace_monitor.ai import OllamaConfig, UnitySVCConfig
from ai_marketplace_monitor.configure import ai_setup
from ai_marketplace_monitor.configure.ai_setup import (
    AISection,
    AISectionProposal,
    AISetupContext,
    CommitOutcome,
    ConfigReadError,
    ProbeResult,
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
from ai_marketplace_monitor.configure.ui import Choice, JsonSetupUI, ScriptedSetupUI

REAL_FETCH_MODELS = ai_setup.fetch_models


@pytest.fixture(autouse=True)
def no_model_listing(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """Setup never lists models over the network in tests; records what it would list."""
    calls: List[Dict[str, Any]] = []

    async def fetch(provider: str, values: Dict[str, Any], timeout: float = 10.0) -> List[str]:
        calls.append({"provider": provider, **values})
        return []

    monkeypatch.setattr(ai_setup, "fetch_models", fetch)
    return calls


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
    api_key = "svcpass_secretvalue123"
    raw: Dict[str, Any] = {"api_key": api_key}
    if model:
        raw["model"] = model
    config = None if problem else UnitySVCConfig(name="unitysvc", api_key=api_key, model=model)
    return AISection("unitysvc", raw, [], config=config, problem=problem)


def use_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr(ai_setup, "_probe_client", lambda backend, timeout: client)


def test_env_var_name() -> None:
    assert env_var_name("${UNITYSVC_API_KEY}") == "UNITYSVC_API_KEY"
    assert env_var_name("svcpass_x") is None
    assert env_var_name(None) is None


async def test_json_setup_ui_uses_serializable_prompt_messages() -> None:
    sent: List[Dict[str, Any]] = []
    answers: Iterator[Dict[str, Any]] = iter(
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
    choice = await ui.choose("Provider?", [Choice("openai", "OpenAI")])
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
            "allow_text": False,
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
    proposal = await propose_ai_section(ScriptedSetupUI(["unitysvc", "", "balanced"]), ctx)

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
    ui = ScriptedSetupUI(["", "premium"])
    proposal = await propose_ai_section(ui, context(tmp_path, [path]), section_name="mine")

    assert proposal is not None
    assert proposal.name == "mine"
    assert proposal.values == {
        "provider": "unitysvc",
        "api_key": "${MY_KEY}",
        "model": "premium",
        "timeout": 5,
    }
    assert proposal.target_file == path
    assert ui.questions == ["UnitySVC base URL", "Model"]  # the provider is not asked


async def test_propose_named_provider_defaults_to_matching_provider(tmp_path: Path) -> None:
    ui = ScriptedSetupUI([""])
    proposal = await propose_ai_section(ui, context(tmp_path), section_name="openai")

    assert proposal is not None
    assert proposal.name == "openai"
    assert proposal.values["api_key"] == "${OPENAI_API_KEY}"
    assert "provider" not in proposal.values
    assert ui.questions == ["Model"]  # ai.openai implies the provider


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
    ui = ScriptedSetupUI(["unitysvc", "", "balanced", "yes"])

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
    ui = ScriptedSetupUI(["unitysvc", "", "balanced", "yes"])

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
    ui = ScriptedSetupUI(["unitysvc", "", "balanced", "yes"])

    assert await configure_ai(ui, [], home=tmp_path / "home") == 0

    assert any("unitysvc works (balanced)." in text for text in ui.said("success"))


async def test_propose_existing_named_section_keeps_its_provider(tmp_path: Path) -> None:
    path = write(
        tmp_path / "config.toml",
        '[ai.main]\nprovider = "openai"\napi_key = "${OPENAI_API_KEY}"\nmodel = "gpt-4o"\n',
    )
    ui = ScriptedSetupUI([""])

    proposal = await propose_ai_section(ui, context(tmp_path, [path]), section_name="main")

    assert proposal is not None
    assert ui.questions == ["Model"]  # no provider question: [ai.main] is an OpenAI section
    assert proposal.values == {
        "provider": "openai",
        "api_key": "${OPENAI_API_KEY}",
        "model": "gpt-4o",
    }


async def test_propose_new_custom_name_asks_provider(tmp_path: Path) -> None:
    ui = ScriptedSetupUI(["anthropic", ""])

    proposal = await propose_ai_section(ui, context(tmp_path), section_name="work")

    assert proposal is not None
    assert proposal.name == "work"
    assert proposal.values["provider"] == "anthropic"
    assert proposal.values["api_key"] == "${ANTHROPIC_API_KEY}"


async def test_propose_plain_ai_targets_section_named_after_provider(tmp_path: Path) -> None:
    path = write(
        tmp_path / "config.toml",
        '[ai.mine]\nprovider = "unitysvc"\napi_key = "${MY_KEY}"\ntimeout = 5\n',
    )
    ctx = context(tmp_path, [path])

    proposal = await propose_ai_section(ScriptedSetupUI(["unitysvc", "", "fast"]), ctx)

    assert proposal is not None
    assert proposal.name == "unitysvc"
    # a new section becomes the default: first, in the file of the current first AI section
    assert proposal.target_file == path and proposal.first
    # a new section: the provider's standard variable, shared settings from [ai.mine]
    assert proposal.values == {"api_key": "${UNITYSVC_API_KEY}", "model": "fast", "timeout": 5}


async def test_propose_plain_ai_never_converts_a_mismatched_section(tmp_path: Path) -> None:
    path = write(
        tmp_path / "config.toml",
        '[ai.unitysvc]\nprovider = "openai"\napi_key = "${OPENAI_API_KEY}"\n',
    )
    ui = ScriptedSetupUI(["unitysvc", "", "balanced"])

    proposal = await propose_ai_section(ui, context(tmp_path, [path]))

    assert proposal is not None
    assert proposal.name == "unitysvc_2"
    assert proposal.values["provider"] == "unitysvc"
    assert proposal.values["api_key"] == "${UNITYSVC_API_KEY}"
    assert any("leaving it unchanged" in text for text in ui.said("warning"))


async def test_propose_hand_made_mismatch_is_kept_and_flagged(tmp_path: Path) -> None:
    path = write(
        tmp_path / "config.toml",
        '[ai.openai]\nprovider = "anthropic"\napi_key = "${ANTHROPIC_API_KEY}"\n',
    )
    ui = ScriptedSetupUI([""])

    proposal = await propose_ai_section(ui, context(tmp_path, [path]), section_name="openai")

    assert proposal is not None
    assert proposal.values["provider"] == "anthropic"
    assert proposal.values["api_key"] == "${ANTHROPIC_API_KEY}"
    assert any("does not match its name" in text for text in ui.said("warning"))


async def test_configure_ai_rejects_providers_it_cannot_set_up(tmp_path: Path) -> None:
    ui = ScriptedSetupUI([])

    assert await configure_ai(ui, [], section_name="gemini", home=tmp_path / "home") == 1
    assert "edited by hand" in ui.said("error")[0]


def test_probe_does_not_scrub_ollama_placeholder_key(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(
        models=["llama3"], create_errors=[RuntimeError("model not found; run `ollama pull`")]
    )
    use_client(monkeypatch, client)
    raw = {"base_url": "http://localhost:11434/v1", "model": "llama3"}
    config = OllamaConfig(name="ollama", base_url=raw["base_url"], model=raw["model"])
    result = probe_ai_section(AISection("ollama", raw, [], config=config))

    assert not result.ok
    assert "ollama pull" in result.message


async def test_after_commit_reports_a_missing_section(tmp_path: Path) -> None:
    ui = ScriptedSetupUI([])
    proposal = AISectionProposal("gone", {"model": "m"}, None, tmp_path / "x.toml")

    assert await ai_setup._after_commit(ui, proposal, context(tmp_path)) is False
    assert "could not be found" in ui.said("error")[0]


async def test_run_in_daemon_thread_returns_and_raises() -> None:
    assert await ai_setup.run_in_daemon_thread(lambda x: x * 2, 21) == 42

    def boom() -> None:
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        await ai_setup.run_in_daemon_thread(boom)


async def test_json_setup_ui_reasks_after_invalid_answers() -> None:
    sent: List[Dict[str, Any]] = []
    replies: Iterator[Dict[str, Any]] = iter(
        [
            {"type": "hello"},
            {"type": "answer", "value": "gemini"},
            {"type": "answer", "value": "openai"},
            {"type": "answer", "value": "maybe"},
            {"type": "answer", "value": "no"},
        ]
    )

    async def send(message: Dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> Dict[str, Any]:
        return next(replies)

    ui = JsonSetupUI(send, receive)

    assert await ui.choose("Provider?", [Choice("openai", "OpenAI")]) == "openai"
    assert await ui.confirm("Write?") is False
    errors = [m["text"] for m in sent if m["type"] == "message" and m["kind"] == "error"]
    assert errors == [
        "Expected an answer message, got 'hello'.",
        "Choose one of: openai.",
        "Answer yes or no.",
    ]
    assert [m["prompt"] for m in sent if m["type"] == "prompt"] == [
        "Provider?",
        "Provider?",
        "Provider?",
        "Write?",
        "Write?",
    ]


async def test_commit_earlier_file_with_other_value_is_not_a_conflict(tmp_path: Path) -> None:
    first = write(tmp_path / "config.toml", '[ai.unitysvc]\nmodel = "fast"\n')
    later = write(tmp_path / "later.toml", '[ai.unitysvc]\nmodel = "premium"\n')
    ctx = context(tmp_path, [first, later])

    outcome = await commit_ai_section(ScriptedSetupUI(["yes"]), proposal(later), ctx)

    assert outcome is CommitOutcome.WRITTEN  # later.toml is read last, so it wins


ANTHROPIC_MODELS = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-4-6", "claude-opus-4-6"]
STALE_ANTHROPIC = """\
[ai.anthropic]
api_key = "${ANTHROPIC_API_KEY}"
model = "claude-sonnet-4-20250514"
"""


@pytest.mark.parametrize(
    "current, default, available, expected",
    [
        ("claude-opus-5-5", "claude-sonnet-5-5", ANTHROPIC_MODELS, "claude-opus-5-5"),
        (None, "claude-sonnet-5-5", ANTHROPIC_MODELS, "claude-sonnet-5-5"),
        ("claude-sonnet-4-20250514", "claude-x", ANTHROPIC_MODELS, "claude-sonnet-5-5"),
        ("claude-opus-4-1", "claude-x", ANTHROPIC_MODELS, "claude-opus-5-5"),
        (None, "gpt-4o", ["o3", "gpt-5", "gpt-4.1"], "gpt-5"),
        (None, "llama3", ["qwen3:8b"], "qwen3:8b"),
        ("deepseek-r1:14b", "x", ["llama3:latest", "deepseek-r1:7b"], "deepseek-r1:7b"),
    ],
)
def test_pick_model(
    current: str | None, default: str, available: List[str], expected: str
) -> None:
    assert ai_setup.pick_model(current, default, available) == expected


def stale_probe(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """First check fails with a model list; the check after writing succeeds."""
    calls: List[str] = []

    def probe(section: AISection) -> ProbeResult:
        calls.append(str(section.raw.get("model")))
        if len(calls) == 1:
            return ProbeResult(
                False, "models", calls[0], f'Model "{calls[0]}" is not available', ANTHROPIC_MODELS
            )
        return ProbeResult(True, "request", calls[-1], "ok", ANTHROPIC_MODELS)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(ai_setup, "probe_ai_section", probe)
    return calls


async def test_configure_ai_offers_to_fix_a_broken_section_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = stale_probe(monkeypatch)
    config = write(tmp_path / "config.toml", STALE_ANTHROPIC)
    ui = ScriptedSetupUI(["", "", "yes"])

    assert await configure_ai(ui, [config], home=tmp_path / "home") == 0

    assert ui.questions[:2] == ["What would you like to do?", "Which model?"]
    assert 'Model "claude-sonnet-4-20250514" is no longer available.' in ui.said("warning")
    assert 'model = "claude-sonnet-5-5"' in config.read_text()
    assert calls == ["claude-sonnet-4-20250514", "claude-sonnet-5-5"]


async def test_model_menu_other_accepts_a_typed_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale_probe(monkeypatch)
    config = write(tmp_path / "config.toml", STALE_ANTHROPIC)
    ui = ScriptedSetupUI(["edit:anthropic", "claude-sonnet-4-6", "yes"])

    assert await configure_ai(ui, [config], home=tmp_path / "home") == 0
    assert 'model = "claude-sonnet-4-6"' in config.read_text()


async def test_broken_section_menu_can_set_up_another_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale_probe(monkeypatch)
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    config = write(tmp_path / "config.toml", STALE_ANTHROPIC)
    ui = ScriptedSetupUI(["new", "unitysvc", "", "balanced", "yes"])

    assert await configure_ai(ui, [config], home=tmp_path / "home") == 0
    assert ui.questions[:2] == ["What would you like to do?", "Which AI do you want to configure?"]
    assert "[ai.unitysvc]" in config.read_text()


async def test_broken_section_menu_quit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stale_probe(monkeypatch)
    config = write(tmp_path / "config.toml", STALE_ANTHROPIC)
    assert await configure_ai(ScriptedSetupUI(["quit"]), [config], home=tmp_path / "h") == 0
    assert config.read_text() == STALE_ANTHROPIC


async def test_model_is_free_text_without_a_model_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ui = ScriptedSetupUI(["anthropic", "", "no", "quit"])
    await configure_ai(ui, [], home=tmp_path / "home")
    assert ui.questions[1] == "Model"


TWO_AIS = """\
[ai.anthropic]
api_key = "${ANTHROPIC_API_KEY}"  # Claude
model = "claude-sonnet-5-5"

[ai.unitysvc]
api_key = "${UNITYSVC_API_KEY}"
model = "balanced"
"""


def probe_by_name(monkeypatch: pytest.MonkeyPatch, ok: Dict[str, bool]) -> List[str]:
    """Probe results by section name; records which sections were checked."""
    checked: List[str] = []

    def probe(section: AISection) -> ProbeResult:
        checked.append(section.name)
        model = str(section.raw.get("model"))
        if ok.get(section.name, True):
            return ProbeResult(True, "request", model, "ok", [])
        return ProbeResult(False, "request", model, f"{section.name} failed", [])

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    monkeypatch.setattr(ai_setup, "probe_ai_section", probe)
    return checked


async def test_only_the_default_ai_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked = probe_by_name(monkeypatch, {})
    config = write(tmp_path / "config.toml", TWO_AIS)
    ui = ScriptedSetupUI([""])  # keep

    assert await configure_ai(ui, [config], home=tmp_path / "home") == 0
    assert checked == ["anthropic"]
    assert "Also configured: unitysvc (used only if anthropic fails)." in ui.said()
    assert config.read_text() == TWO_AIS


async def test_menu_lists_each_other_section_and_create_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe_by_name(monkeypatch, {})
    config = write(tmp_path / "config.toml", TWO_AIS)
    seen: List[List[str]] = []

    class Recording(ScriptedSetupUI):
        async def choose(
            self, prompt: str, options: List[Choice], default: str | None = None, **kw: Any
        ) -> str:
            seen.append([o.label for o in options])
            return await super().choose(prompt, options, default, **kw)

    await configure_ai(Recording(["quit"]), [config], home=tmp_path / "home")
    assert seen[0] == [
        "Keep [ai.anthropic] as is",
        "Update [ai.anthropic]",
        "Make [ai.unitysvc] the default",
        "Create a new AI section",
        "Quit",
    ]


async def test_make_another_section_the_default_then_check_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked = probe_by_name(monkeypatch, {"anthropic": False})
    config = write(tmp_path / "config.toml", TWO_AIS)
    ui = ScriptedSetupUI(["default:unitysvc", "yes", "keep"])

    assert await configure_ai(ui, [config], home=tmp_path / "home") == 0
    assert checked == ["anthropic", "unitysvc"]
    assert [s.name for s in load_ai_sections([config])] == ["unitysvc", "anthropic"]
    assert "# Claude" in config.read_text()
    assert "[ai.unitysvc] is now the default AI." in ui.said("success")
    assert list((tmp_path / "home" / "backups").iterdir())


async def test_make_default_moves_a_section_between_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe_by_name(monkeypatch, {})
    first = write(tmp_path / "a.toml", TWO_AIS.split("[ai.unitysvc]")[0])
    second = write(tmp_path / "b.toml", "[ai.unitysvc]\n" + TWO_AIS.split("[ai.unitysvc]\n")[1])
    ui = ScriptedSetupUI(["default:unitysvc", "yes", "quit"])

    assert await configure_ai(ui, [first, second], home=tmp_path / "home") == 0
    assert [s.name for s in load_ai_sections([first, second])] == ["unitysvc", "anthropic"]
    assert "[ai.unitysvc]" in first.read_text() and "[ai.unitysvc]" not in second.read_text()
    assert any("moves from" in m for m in ui.said())


async def test_declining_make_default_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe_by_name(monkeypatch, {})
    config = write(tmp_path / "config.toml", TWO_AIS)
    ui = ScriptedSetupUI(["default:unitysvc", "no", "quit"])
    assert await configure_ai(ui, [config], home=tmp_path / "home") == 0
    assert config.read_text() == TWO_AIS


async def test_create_new_section_becomes_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe_by_name(monkeypatch, {})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config = write(tmp_path / "config.toml", TWO_AIS)
    ui = ScriptedSetupUI(["new", "openai", "gpt-5", "yes"])

    assert await configure_ai(ui, [config], home=tmp_path / "home") == 0
    assert [s.name for s in load_ai_sections([config])] == ["openai", "anthropic", "unitysvc"]


async def test_no_sections_goes_straight_to_provider_menu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    ui = ScriptedSetupUI(["quit"])
    assert await configure_ai(ui, [], home=tmp_path / "home") == 0
    assert ui.questions == ["Which AI do you want to configure?"]


async def test_named_section_checks_only_that_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked = probe_by_name(monkeypatch, {})
    config = write(tmp_path / "config.toml", TWO_AIS)
    await configure_ai(
        ScriptedSetupUI(["", "no", "<close>"]),
        [config],
        section_name="unitysvc",
        home=tmp_path / "h",
    )
    assert checked == ["unitysvc"]


UNITYSVC_MODELS = ["deepseek-v4-pro", "kimi-k3", "balanced", "coding", "fast", "premium"]


def list_models(monkeypatch: pytest.MonkeyPatch, models: List[str]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    async def fetch(provider: str, values: Dict[str, Any], timeout: float = 10.0) -> List[str]:
        calls.append({"provider": provider, **values})
        return list(models)

    monkeypatch.setattr(ai_setup, "fetch_models", fetch)
    return calls


async def test_unitysvc_model_is_chosen_from_the_listed_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = list_models(monkeypatch, UNITYSVC_MODELS)
    seen: List[List[str]] = []

    class Recording(ScriptedSetupUI):
        async def choose(
            self, prompt: str, options: List[Choice], default: str | None = None, **kw: Any
        ) -> str:
            seen.append([prompt, default or "", *(o.value for o in options)])
            return await super().choose(prompt, options, default, **kw)

    ui = Recording(["unitysvc", "", "kimi-k3"])
    proposal = await propose_ai_section(ui, context(tmp_path))

    assert proposal is not None
    assert proposal.values == {"api_key": "${UNITYSVC_API_KEY}", "model": "kimi-k3"}  # default URL
    assert seen[1][:3] == ["Which model?", "balanced", "balanced"]
    assert set(seen[1][2:]) == set(UNITYSVC_MODELS)
    assert calls[0]["base_url"] == "https://api.svcpass.com/p/llm"


async def test_unitysvc_custom_base_url_is_written_and_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = list_models(monkeypatch, ["balanced"])
    ui = ScriptedSetupUI(
        ["unitysvc", "api.svcpass.com/a/myllm", "https://api.svcpass.com/a/myllm/", ""]
    )
    proposal = await propose_ai_section(ui, context(tmp_path))

    assert proposal is not None
    assert proposal.values["base_url"] == "https://api.svcpass.com/a/myllm"
    assert proposal.values["model"] == "balanced"
    assert calls[0]["base_url"] == "https://api.svcpass.com/a/myllm"
    assert "The URL must start with https:// or http://." in ui.said("warning")


async def test_model_list_from_the_check_is_reused_for_the_same_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_model_listing: List[Dict[str, Any]]
) -> None:
    path = write(
        tmp_path / "config.toml",
        '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\nmodel = "fast"\n',
    )
    ctx = context(tmp_path, [path])
    ctx.probes["unitysvc"] = ProbeResult(True, "request", "fast", "ok", UNITYSVC_MODELS)
    proposal = await propose_ai_section(ScriptedSetupUI(["", ""]), ctx, section_name="unitysvc")

    assert proposal is not None and proposal.values["model"] == "fast"  # current kept
    assert no_model_listing == []  # no second listing


async def test_fetch_models_lists_or_returns_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    models = SimpleNamespace(
        list=lambda: [SimpleNamespace(id="balanced"), SimpleNamespace(id="kimi-k3")]
    )
    monkeypatch.setattr(
        ai_setup, "_probe_client", lambda backend, timeout: SimpleNamespace(models=models)
    )
    values = {"api_key": "${UNITYSVC_API_KEY}", "base_url": "https://api.svcpass.com/p/llm"}
    assert await REAL_FETCH_MODELS("unitysvc", values) == ["balanced", "kimi-k3"]

    def boom(backend: Any, timeout: float) -> Any:
        raise RuntimeError("401")

    monkeypatch.setattr(ai_setup, "_probe_client", boom)
    assert await REAL_FETCH_MODELS("unitysvc", values) == []
    monkeypatch.delenv("UNITYSVC_API_KEY")
    assert await REAL_FETCH_MODELS("unitysvc", values) == []  # key not set: nothing to ask


async def test_json_choice_accepts_typed_text_only_when_allowed() -> None:
    replies = [{"type": "answer", "value": "kimi-k3"}, {"type": "answer", "value": "kimi-k3"}]
    sent: List[Dict[str, Any]] = []

    async def send(message: Dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> Dict[str, Any]:
        return replies.pop(0)

    ui = JsonSetupUI(send, receive)
    options = [Choice("balanced", "balanced")]
    assert await ui.choose("Which model?", options, "balanced", allow_text=True) == "kimi-k3"
    assert sent[-1]["allow_text"] is True
    with pytest.raises(IndexError):  # not allowed: the reply is rejected and asked again
        await ui.choose("Which model?", options, "balanced")


def test_console_choice_accepts_typed_text_only_when_allowed() -> None:
    import asyncio

    from rich.console import Console

    from ai_marketplace_monitor.configure.ui import ConsoleSetupUI

    answers = iter(["qwen3.7-flash", "abc", "1"])
    ui = ConsoleSetupUI(
        console=Console(file=open("/dev/null", "w")),
        read=lambda _: next(answers),
        interactive=True,
    )
    options = [Choice("balanced", "balanced")]
    assert asyncio.run(ui.choose("Which model?", options, allow_text=True)) == "qwen3.7-flash"
    assert asyncio.run(ui.choose("Which model?", options)) == "balanced"  # "abc" re-asked


async def test_fetch_models_tries_without_v1_when_v1_lists_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    urls: List[str] = []

    def client(backend: Any, timeout: float) -> Any:
        url = backend.config.base_url
        urls.append(url)
        found = [] if url.endswith("/v1") else [SimpleNamespace(id="qwen3.7-flash")]
        return SimpleNamespace(models=SimpleNamespace(list=lambda: found))

    monkeypatch.setattr(ai_setup, "_probe_client", client)
    values = {"api_key": "${UNITYSVC_API_KEY}", "base_url": "https://api.svcpass.com/qwen/v1"}
    assert await REAL_FETCH_MODELS("unitysvc", values) == ["qwen3.7-flash"]
    assert urls == ["https://api.svcpass.com/qwen/v1", "https://api.svcpass.com/qwen"]


def test_probe_suggests_v1_when_requests_are_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def client(backend: Any, timeout: float) -> Any:
        v1 = backend.config.base_url.endswith("/v1")

        def create(**kwargs: Any) -> Any:
            if not v1:
                raise status_error(404, "not found")
            return SimpleNamespace()

        return SimpleNamespace(
            models=SimpleNamespace(list=lambda: [SimpleNamespace(id="qwen3.7-flash")]),
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

    monkeypatch.setattr(ai_setup, "_probe_client", client)
    raw = {
        "api_key": "svcpass_x",
        "base_url": "https://api.svcpass.com/qwen",
        "model": "qwen3.7-flash",
    }
    config = UnitySVCConfig(
        name="unitysvc", api_key=raw["api_key"], base_url=raw["base_url"], model=raw["model"]
    )
    result = probe_ai_section(AISection("unitysvc", raw, [], config=config))

    assert not result.ok
    assert result.suggested_base_url == "https://api.svcpass.com/qwen/v1"
    assert "https://api.svcpass.com/qwen/v1 works; use it as base_url" in result.message


async def test_after_commit_offers_the_v1_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    config = write(tmp_path / "config.toml", "")
    results = [
        ProbeResult(False, "request", "m", "use /v1", [], "https://api.svcpass.com/qwen/v1"),
        ProbeResult(True, "request", "m", "ok", []),
    ]
    monkeypatch.setattr(ai_setup, "probe_ai_section", lambda section: results.pop(0))
    ui = ScriptedSetupUI(
        ["unitysvc", "https://api.svcpass.com/qwen", "qwen3.7-flash", "yes", "yes"]
    )

    assert await configure_ai(ui, [config], home=tmp_path / "home") == 0
    assert 'base_url = "https://api.svcpass.com/qwen/v1"' in config.read_text()
    assert "unitysvc works (m)." in ui.said("success")
