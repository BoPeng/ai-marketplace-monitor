"""Tests for `ai_marketplace_monitor`.cli module."""

from typing import List

import pytest
from typer.testing import CliRunner

import ai_marketplace_monitor
from ai_marketplace_monitor import cli

runner = CliRunner()


@pytest.mark.parametrize(
    "options,expected",
    [
        # ([], "ai_marketplace_monitor.cli.main"),
        (["--help"], "Usage: "),
        (
            ["--version"],
            f"AI Marketplace Monitor, version { ai_marketplace_monitor.__version__ }\n",
        ),
    ],
)
def test_command_line_interface(options: List[str], expected: str) -> None:
    """Test the CLI."""
    result = runner.invoke(cli.app, options)
    assert result.exit_code == 0
    assert expected in result.stdout
