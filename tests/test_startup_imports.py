"""Startup must not load heavy packages that the command may never need.

Loading openai, anthropic, inflect and playwright adds about 2,000 modules and several
seconds to every start (much more when Python cannot reuse cached bytecode). They are
imported where they are used instead.
"""

import subprocess
import sys

import pytest

HEAVY = ("openai", "anthropic", "inflect", "playwright")


@pytest.mark.parametrize(
    "module",
    ["ai_marketplace_monitor.cli", "ai_marketplace_monitor.configure.cli"],
)
def test_cli_import_does_not_load_heavy_packages(module: str) -> None:
    code = (
        f"import sys, {module}\n"
        f"print(','.join(sorted({{m.split('.')[0] for m in sys.modules}} & set({HEAVY!r}))))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert loaded == "", f"{module} loads {loaded} at import time"
