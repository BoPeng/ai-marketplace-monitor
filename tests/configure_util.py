"""Helpers for configure builder tests: a fake AI and a builder context from TOML text."""

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from ai_marketplace_monitor.config import load_config_dicts
from ai_marketplace_monitor.configure.playbooks import load_playbooks
from ai_marketplace_monitor.configure.sections import BuilderContext

BASE = """
[ai.unitysvc]
api_key = "svcpass_testkey"

[user.me]
pushbullet_token = "abc"
"""


class FakeAI:
    """Returns queued replies (dicts become JSON); records every message list."""

    def __init__(self, replies: List[Any]) -> None:
        self.replies = list(replies)
        self.calls: List[List[Dict[str, str]]] = []
        self.timeouts: List[Any] = []
        self.config = SimpleNamespace(api_key="svcpass_testkey", name="fake")

    def chat(
        self, messages: List[Dict[str, str]], *, json_mode: bool = False, timeout: Any = None
    ) -> str:
        self.calls.append(messages)
        self.timeouts.append(timeout)
        if not self.replies:
            raise AssertionError("unexpected LLM call")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)


def make_ctx(tmp_path: Path, text: str, replies: List[Any] | None = None) -> BuilderContext:
    path = tmp_path / "config.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    system, user = load_config_dicts([path])
    return BuilderContext(
        files=[path],
        system_cfg=system,
        user_cfg=user,
        backup_dir=tmp_path / "backups",
        playbooks=load_playbooks(["AGENT", "marketplace"]),
        ai=FakeAI(replies or []),  # type: ignore[arg-type]
    )


def reply(
    message: str = "ok",
    values: Dict[str, Any] | None = None,
    action: str = "ask",
    **extra: Any,
) -> Dict[str, Any]:
    return {
        "action": action,
        "message": message,
        "request": extra.pop("request", "r"),
        "values": values or {},
        "unset": extra.pop("unset", []),
        **extra,
    }
