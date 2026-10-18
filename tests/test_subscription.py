import io
import json
import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from PIL import Image

from ai_marketplace_monitor import ai as ai_module
from ai_marketplace_monitor.ai import (
    SubscriptionBackend,
    SubscriptionConfig,
    SubscriptionError,
    rating_and_comment,
)
from ai_marketplace_monitor.config import supported_ai_backends
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.marketplaces.facebook import (
    FacebookItemConfig,
    FacebookMarketplaceConfig,
)

CLAUDE = "claude -p --model sonnet"


class FakeProcess:
    def __init__(self, fake: "FakeCLI", argv: List[str], **kwargs: Any) -> None:
        self.fake, self.argv, self.kwargs = fake, argv, kwargs
        self.pid = 4242
        self.returncode = 0

    def communicate(self, stdin: str | None = None, timeout: float | None = None) -> Any:
        if stdin is None:  # the reap after a kill
            return "", ""
        options = {k: v for k, v in self.kwargs.items() if k not in ("stdin", "stdout", "stderr")}
        call = SimpleNamespace(
            argv=self.argv,
            input=stdin,
            timeout=timeout,
            cwd_existed=Path(self.kwargs["cwd"]).is_dir(),
            image=None,
            **options,
        )
        for arg in self.argv:  # read a photo passed as {image} while it exists
            if arg.endswith("listing.jpg"):
                call.image = Path(arg).read_bytes()
        self.fake.calls.append(call)
        result = self.fake.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, tuple):  # (stdout, stderr, returncode) of a plain CLI
            self.returncode = result[2]
            return result[0], result[1]
        events = [{"type": "system", "subtype": "init"}, {"type": "result", **result}]
        self.returncode = 1 if result.get("is_error") else 0
        return "\n".join(json.dumps(e) for e in events) + "\n", ""

    def __enter__(self) -> "FakeProcess":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class FakeCLI:
    """subprocess.Popen for the AI module."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *results: Any) -> None:
        self.results = list(results)
        self.calls: List[SimpleNamespace] = []
        self.killed: List[int] = []
        monkeypatch.setattr(ai_module.shutil, "which", lambda command: f"/usr/bin/{command}")
        monkeypatch.setattr(ai_module.subprocess, "Popen", lambda argv, **kw: FakeProcess(self, argv, **kw))
        monkeypatch.setattr(ai_module.os, "killpg", lambda pid, sig: self.killed.append(pid))

    @property
    def message(self) -> Any:
        return json.loads(self.calls[-1].input)["message"]


def answer(text: str) -> dict:
    return {"subtype": "success", "is_error": False, "result": text}


def failure(text: str, status: int | None = None) -> dict:
    return {"subtype": "success", "is_error": True, "result": text, "api_error_status": status}


def backend(command: Any = CLAUDE, **kwargs: Any) -> SubscriptionBackend:
    ai = SubscriptionBackend(SubscriptionConfig(name="sub", command=command, **kwargs))
    return ai


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    sleeps: List[float] = []
    monkeypatch.setattr(ai_module.time, "sleep", sleeps.append)
    return sleeps


@pytest.fixture
def unique(listing: Listing, item_config: FacebookItemConfig) -> str:
    suffix = uuid4().hex
    listing.id = f"subscription-test-{suffix}"
    listing.title = f"Subscription test {suffix}"
    listing.image = ""
    item_config.name = f"test-{suffix}"
    return suffix


@pytest.fixture
def photo(monkeypatch: pytest.MonkeyPatch, listing: Listing) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (2000, 1000)).save(buffer, format="PNG")
    get = MagicMock(return_value=SimpleNamespace(content=buffer.getvalue(), raise_for_status=lambda: None))
    monkeypatch.setattr(ai_module.requests, "get", get)
    listing.image = "https://example.com/listing.jpg"


# configuration


def test_subscription_is_a_provider() -> None:
    assert supported_ai_backends["subscription"] is SubscriptionBackend
    config = SubscriptionBackend.get_config(name="s", provider="subscription", command=CLAUDE)
    assert config.command == CLAUDE and config.api_key is None


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"command": CLAUDE, "api_key": "sk"}, "not an api_key"),
        ({}, "needs a command"),
        ({"command": "  "}, "needs a command"),
        ({"command": "claude -p --dangerously-skip-permissions"}, "act without asking"),
        ({"command": "codex exec --full-auto -", "allow_any_command": True}, "act without asking"),
        ({"command": "gemini --yolo", "allow_any_command": True}, "act without asking"),
        ({"command": "gemini --approval-mode=yolo", "allow_any_command": True}, "act without asking"),
        ({"command": "claude -p --allowedTools Bash"}, "sets --allowedTools"),
        ({"command": "claude -p --mcp-config x.json"}, "sets --mcp-config"),
        ({"command": "claude -p --permission-mode=acceptEdits"}, "sets --permission-mode"),
        ({"command": "codex exec -"}, "allow_any_command = true"),
        ({"command": CLAUDE, "keep_env": "ANTHROPIC_API_KEY"}, "keep_env"),
    ],
)
def test_unsafe_or_incomplete_sections_are_refused(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        SubscriptionConfig(name="sub", **kwargs)


def test_commands_aimm_has_no_profile_for_need_consent() -> None:
    config = SubscriptionConfig(name="s", command=["gemini", "-p"], allow_any_command=True)
    assert config.command == ["gemini", "-p"]
    assert SubscriptionConfig(name="s", command="/opt/bin/claude -p").command  # a path to claude


def test_missing_command_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_module.shutil, "which", lambda command: None)
    with pytest.raises(RuntimeError, match="'claude' was not found"):
        backend().connect()


# claude


def test_claude_runs_without_tools_settings_or_billing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        monkeypatch.setenv(var, "1")
    monkeypatch.setenv("HOME_KEEP", "yes")
    fake = FakeCLI(monkeypatch, answer("OK"))
    ai = backend()
    ai.connect()

    assert ai.ask("Hello", "Be brief.") == "OK"
    call = fake.calls[-1]
    argv = call.argv
    assert argv[:4] == ["/usr/bin/claude", "-p", "--model", "sonnet"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert {"--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"} <= set(argv)
    assert argv[argv.index("--system-prompt") + 1] == "Be brief."
    env = call.env
    assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"} & set(env)
    assert env["HOME_KEEP"] == "yes"
    assert call.start_new_session is True and call.cwd_existed and not Path(call.cwd).exists()
    assert "Hello" not in " ".join(argv)  # the prompt is on stdin only
    assert fake.message["content"] == [{"type": "text", "text": "Hello"}]


def test_keep_env_passes_a_billing_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
    fake = FakeCLI(monkeypatch, answer("OK"))
    ai = backend(keep_env=["CLAUDE_CODE_USE_VERTEX"])
    ai.connect()
    ai.ask("Hello", "Be brief.")
    assert fake.calls[-1].env["CLAUDE_CODE_USE_VERTEX"] == "1"


def test_claude_errors_carry_the_api_status(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeCLI(monkeypatch, failure("You've hit your limit", 429))
    ai = backend()
    ai.connect()
    with pytest.raises(SubscriptionError, match="hit your limit") as error:
        ai.ask("Hello", "Be brief.")
    assert error.value.status_code == 429


def test_claude_without_a_result_reports_its_output(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeCLI(monkeypatch, ("", "Not logged in. Run claude.", 1))
    ai = backend()
    ai.connect()
    with pytest.raises(SubscriptionError, match="exited with 1: Not logged in"):
        ai.ask("Hello", "Be brief.")


def test_timeout_kills_the_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCLI(monkeypatch, subprocess.TimeoutExpired(["claude"], 5))
    ai = backend(timeout=5)
    ai.connect()
    with pytest.raises(SubscriptionError, match="did not answer in 5 seconds"):
        ai.ask("Hello", "Be brief.")
    assert fake.killed == [4242]


def test_claude_evaluates_a_listing_with_its_photo(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    photo: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeCLI(monkeypatch, answer("Looks right.\nRating 4: Good match, fair price."))
    ai = backend()
    res = ai.evaluate(listing, item_config, marketplace_config)
    assert (res.score, res.comment) == (4, "Good match, fair price.")
    image, text = fake.message["content"]
    assert image["type"] == "image" and text["text"].endswith(ai_module.IMAGE_NOTE)
    assert listing.title in text["text"]
    assert ai.evaluate(listing, item_config, marketplace_config).score == 4  # cached
    assert len(fake.calls) == 1


def test_failed_evaluation_is_retried_then_given_up(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    clock: List[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeCLI(monkeypatch, failure("Overloaded", 529), answer("Rating 3: Poor match."))
    assert backend().evaluate(listing, item_config, marketplace_config).score == 3
    assert clock == [5]

    item_config.name += "-2"
    FakeCLI(monkeypatch, failure("Overloaded", 529), failure("Overloaded", 529))
    with pytest.raises(RuntimeError, match="failed to evaluate"):
        backend(max_retries=2).evaluate(listing, item_config, marketplace_config)


def test_answer_without_rating_is_invalid(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeCLI(monkeypatch, answer("I cannot tell."))
    with pytest.raises(ValueError, match="invalid response"):
        backend().evaluate(listing, item_config, marketplace_config)


def test_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCLI(monkeypatch, answer("  Two good deals today.  "))
    assert backend().summarize("Summarize this") == "Two good deals today."
    assert fake.calls[-1].timeout == ai_module.SUMMARY_TIMEOUT


# other commands


def test_other_command_reads_stdout_with_the_photo_path(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    photo: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeCLI(monkeypatch, ("Rating 5: Great deal.\n", "", 0))
    ai = backend("codex exec --sandbox read-only -i {image} -", allow_any_command=True)
    assert ai.evaluate(listing, item_config, marketplace_config).score == 5
    call = fake.calls[-1]
    path = call.argv[call.argv.index("-i") + 1]
    assert path.endswith("listing.jpg") and not Path(path).exists()  # removed afterwards
    assert call.image[:2] == b"\xff\xd8"  # the JPEG was there during the call
    assert call.input.startswith("You are a helpful assistant")  # the system prompt leads
    assert listing.title in call.input and ai_module.IMAGE_NOTE in call.input
    assert "--tools" not in call.argv  # claude's options are for claude only


def test_other_command_without_photo_drops_the_image_option(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCLI(monkeypatch, ("OK", "", 0))
    ai = backend(["codex", "exec", "-i", "{image}", "-"], allow_any_command=True)
    ai.connect()
    assert ai.ask("Hello", "Be brief.") == "OK"
    assert fake.calls[-1].argv == ["/usr/bin/codex", "exec", "-"]


def test_other_command_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeCLI(monkeypatch, ("", "auth required", 2))
    ai = backend("gemini -p", allow_any_command=True)
    ai.connect()
    with pytest.raises(SubscriptionError, match="gemini exited with 2: auth required"):
        ai.ask("Hello", "Be brief.")


def test_text_only_command_gets_no_photo(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    photo: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeCLI(monkeypatch, ("Rating 2: Unclear.", "", 0))
    backend("gemini -p", allow_any_command=True).evaluate(listing, item_config, marketplace_config)
    assert ai_module.IMAGE_NOTE not in fake.calls[-1].input
    ai_module.requests.get.assert_not_called()  # type: ignore[attr-defined]


# configure


@pytest.mark.parametrize(
    ("answer_text", "expected"),
    [
        ("Rating 4: Good match.", (4, "Good match.")),
        ("Rating: 2\nNeeds the condition.", (2, "Needs the condition.")),
        ("The case only, not the console.\nRating 1", (1, "The case only, not the console.")),
        ("Rating 5:   Great   deal,\n  low price.", (5, "Great deal, low price.")),
    ],
)
def test_rating_and_comment(answer_text: str, expected: tuple) -> None:
    assert rating_and_comment(answer_text) == expected


def test_configure_chat_explains_a_subscription_cannot_run_it() -> None:
    from ai_marketplace_monitor.configure.agent import ServiceError
    from ai_marketplace_monitor.configure.mirascope_model import model_id

    with pytest.raises(ServiceError, match="cannot run aimm configure"):
        model_id(backend())


def test_probe_checks_with_a_request_and_scrubs_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_marketplace_monitor.configure.ai_setup import AISection, probe_ai_section

    section = AISection(name="sub", raw={"provider": "subscription", "command": CLAUDE}, files=[])
    section.config = SubscriptionConfig(name="sub", provider="subscription", command=CLAUDE)
    fake = FakeCLI(monkeypatch, answer("OK"), failure("bad token sk-ant-api03-abcdefghijklmnopqrstuv", 401))
    ok = probe_ai_section(section)
    assert ok.ok and ok.model == CLAUDE and fake.calls[-1].timeout == 60
    failed = probe_ai_section(section)
    assert not failed.ok and "sk-ant-api03-abcdefghij" not in failed.message
