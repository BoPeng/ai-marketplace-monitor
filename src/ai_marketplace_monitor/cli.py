"""Console script for ai-marketplace-monitor."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated, Any, List, Optional

import rich
import typer
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text

from . import __version__
from .utils import CacheType, amm_home, cache, counter, hilight

app = typer.Typer()


_DEFAULT_CONFIG_TEMPLATE = '''\
# AI Marketplace Monitor — configuration file
#
# Created automatically on first run. Edit in the web UI (or any
# editor) and save — the monitor picks up changes within a second.
#
# Web UI authentication: if [marketplace.facebook] has both `username`
# and `password` set, the web UI requires those credentials to log in.
# Otherwise the web UI starts in first-run setup mode.
#
# See https://ai-marketplace-monitor.readthedocs.io/ for a full reference.

[marketplace.facebook]
# username = "you@example.com"
# password = "your-facebook-password"
search_city = "houston"

[item.example]
# Describe what you want to find. Duplicate this block for each item.
search_phrases = "gopro hero"
# min_price = 50
# max_price = 300

[user.me]
# One of these notification channels is required.
# pushbullet_token = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
'''


def _seed_default_config(path: Path, logger: logging.Logger) -> None:
    """Create a default config file with a minimal template."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        logger.info(
            f"""{hilight("[Config]", "succ")} Created default config at {hilight(str(path))}. Edit it in the web UI to get started."""
        )
    except OSError as e:
        logger.warning(
            f"""{hilight("[Config]", "fail")} Could not create default config at {path}: {e}"""
        )


def _print_webui_banner(info: Any) -> None:
    """Print a prominent panel showing how to reach the web UI."""
    text = Text()
    for url in info.urls:
        text.append("🌐  ", style="bold")
        text.append(url + "\n", style="bold cyan")
    text.append("\n")

    if info.setup_mode:
        text.append("first-run setup — no credentials configured\n", style="bold yellow")
        text.append(
            "\nOpen the URL above and enter your Facebook username\n"
            "and password. They will be saved to your config and\n"
            "used to log in to Facebook. Or click Skip to enter\n"
            "the editor without authentication (loopback only).\n",
            style="dim",
        )
    else:
        text.append("user:      ", style="dim")
        text.append(f"{info.username}\n")
        text.append("password:  ", style="dim")
        text.append("(from [marketplace.facebook] in config)\n", style="dim")

    if info.exposed:
        text.append(
            "\n⚠  Bound to non-loopback interface — exposed on LAN.\n"
            "   Consider TLS via a reverse proxy (nginx, caddy, tailscale).\n",
            style="bold red",
        )

    rich.print(Panel(text, title="[bold]Web UI[/bold]", border_style="cyan", padding=(1, 2)))


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
    webui: Annotated[
        bool,
        typer.Option(
            "--webui/--no-webui",
            help="Run an embedded web UI for editing config and viewing logs.",
        ),
    ] = True,
    webui_host: Annotated[
        str,
        typer.Option("--webui-host", help="Bind address for the web UI. Default: 127.0.0.1"),
    ] = "127.0.0.1",
    webui_port: Annotated[
        int,
        typer.Option("--webui-port", help="Port for the web UI. Default: 8467"),
    ] = 8467,
    webui_log_retention: Annotated[
        int,
        typer.Option(
            "--webui-log-retention",
            help="Number of log messages to retain in the web UI ring buffer.",
        ),
    ] = 2000,
    version: Annotated[
        Optional[bool], typer.Option("--version", callback=version_callback, is_eager=True)
    ] = None,
) -> None:
    """Console script for AI Marketplace Monitor."""
    log_broadcast_handler = None
    log_handlers: list[logging.Handler] = [
        RichHandler(
            markup=True,
            rich_tracebacks=True,
            show_path=False if verbose is None else verbose,
            level="DEBUG" if verbose else "INFO",
        ),
        RotatingFileHandler(
            amm_home / "ai-marketplace-monitor.log",
            encoding="utf-8",
            maxBytes=1024 * 1024,
            backupCount=5,
        ),
    ]
    if webui:
        from .webui.log_handler import LogBroadcastHandler

        log_broadcast_handler = LogBroadcastHandler(capacity=webui_log_retention)
        log_broadcast_handler.setLevel(logging.DEBUG)
        log_handlers.append(log_broadcast_handler)

    logging.basicConfig(
        level="DEBUG",
        format="%(message)s",
        handlers=log_handlers,
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

    webui_server = None
    try:
        # If web UI is on and there are no existing config files, seed
        # the default ~/.ai-marketplace-monitor/config.toml with a
        # template so the user can edit it from the browser on first run.
        if webui and not config_files and not (amm_home / "config.toml").exists():
            _seed_default_config(amm_home / "config.toml", logger)

        monitor = MarketplaceMonitor(config_files, headless, logger)
        if webui and log_broadcast_handler is not None:
            from .webui.server import WebUIConfig, start_webui

            if not monitor.config_files:
                logger.warning(
                    f"""{hilight("[WebUI]", "fail")} No config file available to edit — web UI disabled."""
                )
            else:
                try:
                    webui_server, webui_info = start_webui(
                        WebUIConfig(
                            host=webui_host,
                            port=webui_port,
                            config_files=monitor.config_files,
                            log_handler=log_broadcast_handler,
                        ),
                        logger=logger,
                    )
                    # Don't race the web UI for Facebook credentials —
                    # wait for them to land in the config before
                    # launching the Playwright browser.
                    monitor.defer_login_until_credentials = True
                    _print_webui_banner(webui_info)
                except Exception as e:
                    logger.error(
                        f"""{hilight("[WebUI]", "fail")} Failed to start web UI: {e}"""
                    )
        monitor.start_monitor()
    except KeyboardInterrupt:
        rich.print("Exiting...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"""{hilight("[Monitor]", "fail")} {e}""")
        raise
        sys.exit(1)
    finally:
        if webui_server is not None:
            webui_server.stop()
        monitor.stop_monitor()
        rich.print(counter)


if __name__ == "__main__":
    app()  # pragma: no cover
