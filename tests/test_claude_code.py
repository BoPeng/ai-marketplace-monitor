import io
import json
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
    ClaudeCodeBackend,
    ClaudeCodeConfig,
    ClaudeCodeError,
    rating_and_comment,
)
from ai_marketplace_monitor.config import supported_ai_backends
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.marketplaces.facebook import (
    FacebookItemConfig,
    FacebookMarketplaceConfig,
)


class FakeClaude:
    """subprocess.run for the AI module: answers like ``claude -p --output-format stream-json``."""

    def __init__(self: "FakeClaude", monkeypatch: pytest.MonkeyPatch, *results: Any) -> None:
        self.results = list(results)
        self.calls: List[SimpleNamespace] = []
        monkeypatch.setattr(ai_module.shutil, "which", lambda command: f"/usr/bin/{command}")
        monkeypatch.setattr(ai_module.subprocess, "run", self.run)

    def run(self: "FakeClaude", command: List[str], **kwargs: Any) -> SimpleNamespace:
        self.calls.append(SimpleNamespace(command=command, cwd_existed=Path(kwargs["cwd"]).is_dir(), **kwargs))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, SimpleNamespace):
            return result
        events = [{"type": "system", "subtype": "init"}, {"type": "result", **result}]
        return SimpleNamespace(
            returncode=1 if result.get("is_error") else 0,
            stdout="\n".join(json.dumps(event) for event in events) + "\n",
            stderr="",
        )

    @property
    def message(self: "FakeClaude") -> dict[str, Any]:
        """The user message of the last request."""
        return json.loads(self.calls[-1].input)["message"]


def answer(text: str) -> dict[str, Any]:
    return {"subtype": "success", "is_error": False, "result": text}


def failure(text: str, status: int | None = None) -> dict[str, Any]:
    return {"subtype": "success", "is_error": True, "result": text, "api_error_status": status}


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    """time.sleep for the AI module, without waiting; the list of seconds slept."""
    sleeps: List[float] = []
    monkeypatch.setattr(ai_module.time, "sleep", sleeps.append)
    return sleeps


@pytest.fixture
def unique(
    listing: Listing, item_config: FacebookItemConfig
) -> str:  # a listing no earlier test has cached an answer for
    suffix = uuid4().hex
    listing.id = f"claude-code-test-{suffix}"
    listing.title = f"Claude Code test {suffix}"
    listing.image = ""
    item_config.name = f"test-{suffix}"
    return suffix


def test_claude_code_is_a_provider() -> None:
    assert supported_ai_backends["claude_code"] is ClaudeCodeBackend
    config = ClaudeCodeBackend.get_config(name="claude", provider="claude_code")
    assert config.command == "claude" and config.api_key is None


def test_claude_code_takes_no_api_key() -> None:
    with pytest.raises(ValueError, match="not an api_key"):
        ClaudeCodeConfig(name="claude", api_key="sk-ant-test")


def test_claude_code_needs_a_command() -> None:
    with pytest.raises(ValueError, match="non-empty string command"):
        ClaudeCodeConfig(name="claude", command=" ")


def test_missing_claude_command_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_module.shutil, "which", lambda command: None)
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name="claude", command="my-claude"))
    with pytest.raises(RuntimeError, match="'my-claude' was not found"):
        ai.connect()


def test_claude_runs_without_tools_settings_or_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-billed")
    fake = FakeClaude(monkeypatch, answer("OK"))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name="claude", model="opus"))
    ai.connect()

    assert ai.ask("Hello", "Be brief.") == "OK"
    call = fake.calls[-1]
    command = call.command
    assert command[:2] == ["/usr/bin/claude", "-p"]
    # listings are untrusted: no tools, MCP servers, settings (hooks) or skills
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--setting-sources") + 1] == ""
    assert {"--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"} <= set(
        command
    )
    assert command[command.index("--model") + 1] == "opus"
    assert command[command.index("--system-prompt") + 1] == "Be brief."
    # the subscription, not the API key, pays; in an empty directory without a CLAUDE.md
    assert "ANTHROPIC_API_KEY" not in call.env
    assert call.cwd_existed and not Path(call.cwd).exists()
    assert call.timeout == ClaudeCodeBackend.default_timeout
    assert fake.message["content"] == [{"type": "text", "text": "Hello"}]


def test_claude_code_default_model_is_sonnet(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClaude(monkeypatch, answer("OK"))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name="claude", timeout=30))
    ai.connect()
    ai.ask("Hello", "Be brief.")
    command = fake.calls[-1].command
    assert command[command.index("--model") + 1] == "sonnet"
    assert fake.calls[-1].timeout == 30


def test_claude_errors_carry_the_api_status(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClaude(monkeypatch, failure("You've hit your limit", 429))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name="claude"))
    ai.connect()
    with pytest.raises(ClaudeCodeError, match="hit your limit") as error:
        ai.ask("Hello", "Be brief.")
    assert error.value.status_code == 429


def test_claude_without_a_result_reports_its_output(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClaude(
        monkeypatch, SimpleNamespace(returncode=1, stdout="", stderr="Not logged in. Run claude.")
    )
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name="claude"))
    ai.connect()
    with pytest.raises(ClaudeCodeError, match="exited with 1: Not logged in"):
        ai.ask("Hello", "Be brief.")


def test_claude_timeout_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClaude(monkeypatch, subprocess.TimeoutExpired(["claude"], 5))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name="claude", timeout=5))
    ai.connect()
    with pytest.raises(ClaudeCodeError, match="did not answer in 5 seconds"):
        ai.ask("Hello", "Be brief.")


def test_claude_code_evaluates_a_listing(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeClaude(monkeypatch, answer("Looks right.\nRating 4: Good match, fair price."))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name=f"claude-{unique}"))

    res = ai.evaluate(listing, item_config, marketplace_config)
    assert (res.score, res.comment, res.name) == (4, "Good match, fair price.", f"claude-{unique}")
    assert listing.title in fake.message["content"][0]["text"]
    # the answer is cached: no second request
    assert ai.evaluate(listing, item_config, marketplace_config).score == 4
    assert len(fake.calls) == 1


def test_claude_code_sends_the_listing_photo(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (2000, 1000)).save(buffer, format="PNG")
    get = MagicMock(
        return_value=SimpleNamespace(content=buffer.getvalue(), raise_for_status=lambda: None)
    )
    monkeypatch.setattr(ai_module.requests, "get", get)
    listing.image = "https://example.com/listing.jpg"
    fake = FakeClaude(monkeypatch, answer("Rating 5: Great deal."))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name=f"claude-{unique}"))

    assert ai.evaluate(listing, item_config, marketplace_config).score == 5
    image, text = fake.message["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    assert text["text"].endswith(ai_module.IMAGE_NOTE)


def test_claude_code_retries_a_failed_evaluation(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    clock: List[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeClaude(monkeypatch, failure("Overloaded", 529), answer("Rating 3: Poor match."))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name=f"claude-{unique}"))

    assert ai.evaluate(listing, item_config, marketplace_config).score == 3
    assert len(fake.calls) == 2 and clock == [5]


def test_claude_code_gives_up_after_retries(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    clock: List[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClaude(monkeypatch, failure("Overloaded", 529), failure("Overloaded", 529))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name=f"claude-{unique}", max_retries=2))

    with pytest.raises(RuntimeError, match="failed to evaluate"):
        ai.evaluate(listing, item_config, marketplace_config)


def test_claude_code_answer_without_rating_is_invalid(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    unique: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClaude(monkeypatch, answer("I cannot tell."))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name=f"claude-{unique}"))

    with pytest.raises(ValueError, match="invalid response"):
        ai.evaluate(listing, item_config, marketplace_config)


def test_claude_code_summarizes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClaude(monkeypatch, answer("  Two good deals today.  "))
    ai = ClaudeCodeBackend(ClaudeCodeConfig(name="claude-summary"))

    assert ai.summarize("Summarize this") == "Two good deals today."
    assert fake.calls[-1].timeout == ai_module.SUMMARY_TIMEOUT
    command = fake.calls[-1].command
    assert command[command.index("--system-prompt") + 1] == ai_module.SUMMARY_SYSTEM


@pytest.mark.parametrize(
    ("answer_text", "expected"),
    [
        ("Rating 4: Good match.", (4, "Good match.")),
        ("Rating: 2\nNeeds the condition.", (2, "Needs the condition.")),
        ("The case only, not the console.\nRating 1", (1, "The case only, not the console.")),
        ("Rating 5:   Great   deal,\n  low price.", (5, "Great deal, low price.")),
    ],
)
def test_rating_and_comment(answer_text: str, expected: tuple[int, str]) -> None:
    assert rating_and_comment(answer_text) == expected


def test_configure_chat_explains_claude_code_cannot_run_it() -> None:
    from ai_marketplace_monitor.configure.agent import ServiceError
    from ai_marketplace_monitor.configure.mirascope_model import model_id

    ai = ClaudeCodeBackend(ClaudeCodeConfig(name="claude"))
    with pytest.raises(ServiceError, match="cannot run aimm configure"):
        model_id(ai)


def test_probe_checks_claude_code_with_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_marketplace_monitor.configure.ai_setup import AISection, probe_ai_section

    raw = {"provider": "claude_code"}
    section = AISection(name="claude", raw=raw, files=[])
    section.config = ClaudeCodeConfig(name="claude", provider="claude_code")

    fake = FakeClaude(monkeypatch, answer("OK"), failure("Not logged in", 401))
    ok = probe_ai_section(section)
    assert ok.ok and ok.model == "sonnet"
    assert fake.calls[-1].timeout == 60

    failed = probe_ai_section(section)
    assert not failed.ok and "Not logged in" in failed.message
