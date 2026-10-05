"""Helpers for configure tests: a workspace from TOML text and a scripted fake model."""

import textwrap
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Tuple, Union

from ai_marketplace_monitor.configure.agent import ModelReply, ServiceError
from ai_marketplace_monitor.configure.marketplace import MarketplaceToolkit
from ai_marketplace_monitor.configure.toolkits import Toolkit
from ai_marketplace_monitor.configure.ui import ScriptedSetupUI
from ai_marketplace_monitor.configure.workspace import Workspace

BASE = """
[ai.unitysvc]
api_key = "svcpass_testkey"

[user.me]
pushbullet_token = "abc"
"""

ONE_ITEM = (
    BASE
    + """
[marketplace.facebook]
search_city = "houston"

[item.example]
search_phrases = "road bike"
min_price = 50
max_price = 300
"""
)


def url(code: str) -> str:
    """A Facebook Marketplace results URL for a location code, as a user would paste it."""
    return f"https://www.facebook.com/marketplace/{code}/search?query=bike"


Call = Tuple[str, Dict[str, Any]]
# a scripted model step: tool calls, a plain-text reply, or a service failure
Step = Union[List[Call], str, ServiceError]


async def make_ws(
    tmp_path: Path,
    text: str,
    answers: List[str] | None = None,
    toolkits: Dict[str, Toolkit] | None = None,
    extra_playbooks: List[str] | None = None,
) -> Workspace:
    path = tmp_path / "config.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    ws = Workspace(
        ui=ScriptedSetupUI(answers or []),
        files=[path],
        home=tmp_path,
        toolkits=toolkits or {"marketplace": MarketplaceToolkit()},
    )
    await ws.load(extra_playbooks or [])
    return ws


def ui_of(ws: Workspace) -> ScriptedSetupUI:
    assert isinstance(ws.ui, ScriptedSetupUI)
    return ws.ui


class FakeModel:
    """A ModelSession that replays scripted steps.

    Tool calls run through the same tool functions the Mirascope adapter receives.
    """

    def __init__(
        self,
        steps: List[Step],
        tools: List[Callable[..., Awaitable[Dict[str, Any]]]] | None = None,
        stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self.steps = list(steps)
        self.tools = {fn.__name__: fn for fn in tools or []}
        self.stop = stop
        self.outputs: List[Tuple[str, Dict[str, Any]]] = []  # (tool, result)
        self.user_texts: List[str] = []
        self.system = ""
        self.opening = ""

    def bind(
        self, tools: List[Callable[..., Awaitable[Dict[str, Any]]]], stop: Callable[[], bool]
    ) -> "FakeModel":
        self.tools = {fn.__name__: fn for fn in tools}
        self.stop = stop
        return self

    def _next(self) -> ModelReply:
        if not self.steps:
            raise AssertionError("unexpected model call")
        step = self.steps.pop(0)
        if isinstance(step, ServiceError):
            raise step
        if isinstance(step, str):
            return ModelReply(text=step)
        return ModelReply(tool_calls=list(step))

    async def start(self, system: str, user: str) -> ModelReply:
        self.system, self.opening = system, user
        return self._next()

    async def run_tools(self, reply: ModelReply) -> ModelReply:
        for name, args in reply.tool_calls:
            if name not in self.tools:
                raise AssertionError(f"tool {name} not offered")
            self.outputs.append((name, await self.tools[name](**args)))
            if self.stop():
                return ModelReply()
        return self._next()

    async def reply_text(self, reply: ModelReply, text: str) -> ModelReply:
        self.user_texts.append(text)
        return self._next()

    async def retry(self) -> ModelReply:
        return self._next()

    def results(self, tool: str) -> List[Dict[str, Any]]:
        return [out for name, out in self.outputs if name == tool]
