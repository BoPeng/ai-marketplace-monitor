"""Shared helpers for CLI command implementations."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import rich
import typer
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text

from .. import __version__
from ..utils import amm_home, cache, cache_corrupted_message, hilight, is_cache_broken

DEFAULT_CONFIG_TEMPLATE = """\
# AI Marketplace Monitor — configuration file
#
# Created automatically on first run. Edit in the web UI (or any
# editor) and save — the monitor picks up changes within a second.
#
# The web UI requires no password on localhost (127.0.0.1). To expose
# it on a network interface (--webui-host), set username and password
# below or via FACEBOOK_USERNAME / FACEBOOK_PASSWORD env vars.
#
# See https://ai-marketplace-monitor.readthedocs.io/ for a full reference.

[marketplace.facebook]
username = "${FACEBOOK_USERNAME}"
password = "${FACEBOOK_PASSWORD}"
search_city = "houston"

[item.example]
# Describe what you want to find. Duplicate this block for each item.
search_phrases = "gopro hero"
# min_price = 50
# max_price = 300

[user.me]
# One of these notification channels is required.
# pushbullet_token = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
"""


def seed_default_config(path: Path, logger: logging.Logger) -> None:
    """Create a default config file with a minimal template."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        logger.info(
            f"""{hilight("[Config]", "succ")} Created default config at {hilight(str(path))}. Edit it in the web UI to get started."""
        )
    except OSError as e:
        logger.warning(
            f"""{hilight("[Config]", "fail")} Could not create default config at {path}: {e}"""
        )


def setup_logging(
    verbose: bool | None, *, webui: bool, webui_log_retention: int = 2000
) -> tuple[logging.Logger, Any | None]:
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
        from ..webui.log_handler import LogBroadcastHandler

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
    return logger, log_broadcast_handler


def print_webui_banner(info: Any) -> None:
    """Print a prominent panel showing how to reach the web UI."""
    text = Text()
    for url in info.urls:
        text.append("🌐  ", style="bold")
        text.append(url + "\n", style="bold cyan")
    text.append("\n")

    if info.exposed:
        text.append("user:     ", style="dim")
        text.append(f"{info.username}\n")
        text.append("password: ", style="dim")
        text.append("(from marketplace config or environment)\n", style="dim")
        text.append(
            "\n⚠  Bound to non-loopback interface — exposed on LAN.\n"
            "   Consider TLS via a reverse proxy (nginx, caddy, tailscale).\n",
            style="bold red",
        )
    else:
        text.append("No password required (local access only).\n", style="dim")

    rich.print(Panel(text, title="[bold]Web UI[/bold]", border_style="cyan", padding=(1, 2)))


def require_readable_cache(logger: logging.Logger) -> None:
    """Stop with how to fix it when the cache database cannot be read."""
    if is_cache_broken(cache):
        logger.error(
            f"""{hilight("[Cache]", "fail")} """
            + cache_corrupted_message(amm_home, cache.error)  # type: ignore[attr-defined]
        )
        raise typer.Exit(1)
