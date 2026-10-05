"""Console script for interactive configuration helpers."""

import asyncio
from pathlib import Path
from typing import Annotated, List

import rich
import typer

from .ai_setup import ConsoleSetupUI, configure_ai, resolve_setup_config_files

app = typer.Typer()


def _ai_section_name(section: str) -> str | None:
    if section == "ai":
        return None
    if section.startswith("ai."):
        name = section.split(".", 1)[1]
        if name:
            return name
    raise typer.BadParameter("Only 'ai' and 'ai.<name>' are supported for now.")


@app.command()
def main(
    section: Annotated[
        str,
        typer.Argument(help="Section to configure. Currently supports only 'ai' or 'ai.<name>'."),
    ] = "ai",
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
        section_name = _ai_section_name(section)
        ui = ConsoleSetupUI()
        files = resolve_setup_config_files(config_files)
    except (RuntimeError, FileNotFoundError, typer.BadParameter) as e:
        rich.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    raise typer.Exit(asyncio.run(configure_ai(ui, files, section_name=section_name)))


if __name__ == "__main__":
    app()  # pragma: no cover
