"""Console script for interactive configuration helpers."""

import asyncio
from pathlib import Path
from typing import Annotated, List, Optional

import rich
import typer

from .ai_setup import ConsoleSetupUI, resolve_setup_config_files
from .configure import (
    ConfigureAddressError,
    configure_front_door,
    configure_section,
    validate_section_address,
)

app = typer.Typer()


@app.command()
def main(
    section: Annotated[
        Optional[str],
        typer.Argument(
            help=(
                "Optional section to configure. Currently supports 'ai', "
                "'ai.<name>', 'item', or 'item.<name>'."
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
    try:
        if section is not None:
            validate_section_address(section)
        ui = ConsoleSetupUI()
        files = resolve_setup_config_files(config_files)
        exit_code = (
            asyncio.run(configure_front_door(ui, files))
            if section is None
            else asyncio.run(configure_section(ui, files, section))
        )
    except (RuntimeError, FileNotFoundError, ConfigureAddressError) as e:
        rich.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()  # pragma: no cover
