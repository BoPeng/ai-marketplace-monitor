"""Console script for ai-marketplace-monitor."""

import logging
import os
import sys
import time
from typing import Annotated, Optional

import rich
import tomllib
import typer
from rich.logging import RichHandler

from . import __version__
from .ai_marketplace_monitor import MarketplaceMonitor

FORMAT = "%(message)s"
logging.basicConfig(level="NOTSET", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()])

logger = logging.getLogger("monitor")


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
        typer.echo(f"ai-marketplace-monitor, version {__version__}")
        raise typer.Exit()


@app.command()
def main(
    config_file: Annotated[
        str, typer.Option("-r", "--config", help="Path to the configuration file in TOML format.")
    ] = "config.toml",
    headless: Annotated[
        Optional[bool],
        typer.Option("--headless", help="If set to true, will not show the browser window."),
    ] = False,
    version: Annotated[
        Optional[bool], typer.Option("--version", callback=version_callback, is_eager=True)
    ] = None,
) -> None:
    """Console script for ai-marketplace-monitor."""
    if not os.path.isfile(config_file):
        sys.exit(f"Config file {config_file} does not exist.")

    try:
        with open(config_file, "rb") as f:
            config = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        rich.print(f"Error parsing config file {config_file}: {e}")
        sys.exit(1)

    # checking if the config file contains a [marketplace.xxx] section
    for required_section in ["facebook", "user"]:
        if required_section not in config:
            rich.print(
                f"Config file {config_file} does not contain a [{required_section}] section."
            )
            sys.exit(1)
    #
    while True:
        try:
            MarketplaceMonitor(config_file, headless, logger).monitor()
        except KeyboardInterrupt:
            rich.print("Exiting...")
            sys.exit(0)
        # if the monitoring tool fails for whatever reason, wait for 60 seconds and starts again
        time.sleep(60)  # Wait for 60 seconds before checking again


if __name__ == "__main__":
    app()  # pragma: no cover
