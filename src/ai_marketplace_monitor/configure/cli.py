"""Console script for interactive configuration helpers."""

import asyncio
from pathlib import Path
from typing import Annotated, Any, Coroutine, List, Optional

import rich
import typer

from ..config import resolve_config_files
from .flow import (
    ConfigureAddressError,
    configure_front_door,
    configure_section,
    validate_section_address,
)
from .ui import ConsoleSetupUI

app = typer.Typer()


def _run(coro: Coroutine[Any, Any, int]) -> int:
    """Run the setup coroutine; Ctrl-C anywhere (prompt or network check) exits cleanly.

    ``asyncio.run`` installs its own SIGINT handler, which cancels the task but does not
    interrupt a blocking ``input()``; a plain event loop keeps Python's default handler.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    except KeyboardInterrupt:
        rich.print("Cancelled.")
        return 0
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


def run_configure_cli(
    section: str | None,
    config_files: List[Path] | None,
) -> None:
    """Run the interactive configuration command."""
    try:
        if section is not None:
            validate_section_address(section)
        ui = ConsoleSetupUI()
        files = resolve_config_files(config_files)
        exit_code = _run(
            configure_front_door(ui, files)
            if section is None
            else configure_section(ui, files, section)
        )
    except (RuntimeError, FileNotFoundError, ConfigureAddressError) as e:
        rich.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    raise typer.Exit(exit_code)


@app.command()
def main(
    section: Annotated[
        Optional[str],
        typer.Argument(
            help=(
                "Optional section to configure, e.g. 'ai', 'ai.<name>', 'marketplace', "
                "'item.<name>', 'notification', 'user.<name>', 'region', 'translation', "
                "or 'monitor'."
            )
        ),
    ] = None,
    config_files: Annotated[
        List[Path] | None,
        typer.Option(
            "-r",
            "--config",
            "--config-file",
            help="Path to one or more configuration files in TOML format.",
        ),
    ] = None,
) -> None:
    """Interactively add or update supported config sections."""
    run_configure_cli(section, config_files)


if __name__ == "__main__":
    app()  # pragma: no cover
