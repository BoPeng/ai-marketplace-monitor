"""Console script for ai-marketplace-monitor."""

import logging
import sys
import time
from typing import Annotated, List, Optional

import rich
import typer
from rich.logging import RichHandler

from . import __version__
from .ai_marketplace_monitor import MarketplaceMonitor

app = typer.Typer()


def version_callback(value: bool) -> None:
    """Callback function for the --version option.

    Parameters:
        - value: The value provided for the --version option.

    Raises:
        - typer.Exit: Raises an Exit exception if the --version option is provided,
        printing the Awesome CLI version and exiting the program.
    """
    if value:
        typer.echo(f"AI Marketplace Monitor, version {__version__}")
        raise typer.Exit()


@app.command()
def main(
    config_files: Annotated[
        List[str] | None,
        typer.Option(
            "-r",
            "--config",
            help="Path to one or more configuration files in TOML format. `~/.ai-marketplace-monitor/config.toml will always be read.",
        ),
    ] = None,
    headless: Annotated[
        Optional[bool],
        typer.Option("--headless", help="If set to true, will not show the browser window."),
    ] = False,
    clear_cache: Annotated[
        Optional[bool],
        typer.Option("--clear-cache", help="Remove all saved items and treat all items as new."),
    ] = False,
    verbose: Annotated[
        Optional[bool],
        typer.Option("--verbose", "-v", help="If set to true, will show debug messages."),
    ] = False,
    version: Annotated[
        Optional[bool], typer.Option("--version", callback=version_callback, is_eager=True)
    ] = None,
) -> None:
    """Console script for AI Marketplace Monitor."""
    logging.basicConfig(
        level="DEBUG" if verbose else "INFO",
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(markup=True)],
    )

    logger = logging.getLogger("monitor")

    while True:
        try:
            MarketplaceMonitor(config_files, headless, clear_cache, logger).monitor()
        except KeyboardInterrupt:
            rich.print("Exiting...")
            sys.exit(0)
        # if the monitoring tool fails for whatever reason, wait for 60 seconds and starts again
        time.sleep(60)  # Wait for 60 seconds before checking again


if __name__ == "__main__":
    app()  # pragma: no cover
