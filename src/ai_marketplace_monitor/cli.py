"""Console script for ai-marketplace-monitor."""

import logging
import sys
from logging import FileHandler
from pathlib import Path
from typing import Annotated, List, Optional

import rich
import typer
from rich.logging import RichHandler

from . import __version__
from .utils import CacheType, amm_home, cache, counter, hilight

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
        List[Path] | None,
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
        Optional[str],
        typer.Option(
            "--clear-cache",
            help=(
                "Remove all or selected category of cached items and treat all queries as new. "
                f"""Allowed cache types are {", ".join([x.value for x in CacheType])} and all """
            ),
        ),
    ] = None,
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
            help="Item to check for URLs specified --check. You will be prmopted for each URL if unspecified and there are multiple items to search.",
        ),
    ] = None,
    version: Annotated[
        Optional[bool], typer.Option("--version", callback=version_callback, is_eager=True)
    ] = None,
) -> None:
    """Console script for AI Marketplace Monitor."""
    logging.basicConfig(
        level="DEBUG",
        # format="%(name)s %(message)s",
        format="%(message)s",
        handlers=[
            RichHandler(
                markup=True,
                rich_tracebacks=True,
                show_path=False if verbose is None else verbose,
                level="DEBUG" if verbose else "INFO",
            ),
            FileHandler(amm_home / "ai-marketplace-monitor.log", encoding="utf-8"),
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

    if clear_cache is not None:
        if clear_cache == "all":
            cache.clear()
        elif clear_cache in [x.value for x in CacheType]:
            cache.evict(tag=clear_cache)
        else:
            logger.error(
                f"""{hilight("[Clear Cache]", "fail")} {clear_cache} is not a valid cache type. Allowed cache types are {", ".join([x.value for x in CacheType])} and all """
            )
            sys.exit(1)
        logger.info(f"""{hilight("[Clear Cache]", "succ")} Cache cleared.""")
        sys.exit(0)

    # make --version a bit faster by lazy loading of MarketplaceMonitor
    from .monitor import MarketplaceMonitor

    if items is not None:
        try:
            monitor = MarketplaceMonitor(config_files, headless, logger)
            monitor.check_items(items, for_item)
        except Exception as e:
            logger.error(f"""{hilight("[Check]", "fail")} {e}""")
            raise
        finally:
            monitor.stop_monitor()

        sys.exit(0)

    try:
        monitor = MarketplaceMonitor(config_files, headless, logger)
        monitor.start_monitor()
    except KeyboardInterrupt:
        rich.print("Exiting...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"""{hilight("[Monitor]", "fail")} {e}""")
        raise
        sys.exit(1)
    finally:
        monitor.stop_monitor()
        rich.print(counter)


if __name__ == "__main__":
    app()  # pragma: no cover
