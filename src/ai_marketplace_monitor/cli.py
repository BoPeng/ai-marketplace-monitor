"""Console script for ai-marketplace-monitor."""

import logging
import sys
from typing import Annotated, List, Optional

import rich
import typer
from rich.logging import RichHandler

from . import __version__
from .monitor import MarketplaceMonitor
from .utils import hilight

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
    disable_javascript: Annotated[
        Optional[bool],
        typer.Option(
            "--disable-javascript",
            help="Disable javascript of the browser.",
        ),
    ] = None,
    clear_cache: Annotated[
        Optional[bool],
        typer.Option("--clear-cache", help="Remove all saved items and treat all items as new."),
    ] = False,
    verbose: Annotated[
        Optional[bool],
        typer.Option("--verbose", "-v", help="If set to true, will show debug messages."),
    ] = False,
    items: Annotated[
        List[str] | None,
        typer.Option(
            "--check",
            help="""Check one or more cached items by their id or URL,
                and list why the item was accepted or denied.""",
        ),
    ] = None,
    for_item: Annotated[
        Optional[str],
        typer.Option(
            "--for",
            help="Item to check for URLs specified --check. If unspecified, the URLs will be checked against all configured items.",
        ),
    ] = None,
    version: Annotated[
        Optional[bool], typer.Option("--version", callback=version_callback, is_eager=True)
    ] = None,
) -> None:
    """Console script for AI Marketplace Monitor."""
    logging.basicConfig(
        level="DEBUG" if verbose else "INFO",
        # format="%(name)s %(message)s",
        format="%(message)s",
        datefmt="[%x %H:%m]",
        handlers=[
            RichHandler(
                markup=True, rich_tracebacks=True, show_path=False if verbose is None else verbose
            )
        ],
    )

    # remove logging from other packages.
    for logger_name in (
        "asyncio",
        "openai._base_client",
        "httpcore.connection",
        "httpcore.http11",
        "httpx",
    ):
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    logger = logging.getLogger("monitor")
    logger.info(
        f"""{hilight("[VERSION]", "info")} AI Marketplace Monitor, version {hilight(__version__, "name")}"""
    )

    if items is not None:
        try:
            MarketplaceMonitor(
                config_files, headless, disable_javascript, False, logger
            ).check_items(items, for_item)
        except Exception as e:
            logger.error(f"""{hilight("[Check]", "fail")} {e}""")
            raise
        sys.exit(0)

    try:
        monitor = MarketplaceMonitor(
            config_files, headless, disable_javascript, clear_cache, logger
        )
        monitor.start_monitor()
    except KeyboardInterrupt:
        rich.print("Exiting...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"""{hilight("[Monitor]", "fail")} {e}""")
        sys.exit(1)
    finally:
        monitor.stop_monitor()


if __name__ == "__main__":
    app()  # pragma: no cover
