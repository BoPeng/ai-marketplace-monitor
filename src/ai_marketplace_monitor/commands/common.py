"""Shared helpers for CLI command implementations."""

import logging
import os
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
# aimm reads these environment variables (in Docker, pass them to the
# container, e.g. in the environment of a docker-compose.yml):
#
#   FACEBOOK_USERNAME, FACEBOOK_PASSWORD  your Facebook login. They also
#       protect the web UI when it is exposed on a network (--webui-host),
#       as in Docker. On localhost (127.0.0.1) the web UI needs no password.
#   UNITYSVC_API_KEY  one key from https://unitysvc.com for the AI that
#       rates listings and for the email and phone/chat notifications.
#
# See https://ai-marketplace-monitor.readthedocs.io/ for a full reference.

[marketplace.facebook]
# Logs in with FACEBOOK_USERNAME and FACEBOOK_PASSWORD.
search_city = "houston"

[item.example]
# Describe what you want to find. Duplicate this block for each item.
search_phrases = "gopro hero"
# min_price = 50
# max_price = 300

[ai.unitysvc]
# Rates each listing, including its main photo.
api_key = "${UNITYSVC_API_KEY}"
model = "balanced"

[notification.unitysvc_email]
# Full email with photos, sent to the address registered with UnitySVC.
smtp_server = "smtp.svcpass.com"
smtp_username = "smtp-to-mailbox"
smtp_password = "${UNITYSVC_API_KEY}"
with_description = true

[notification.unitysvc]
# Short messages to the UnitySVC inbox and the destination saved in
# UnitySVC (Discord, Slack, SMS, phone push, ...).
unitysvc_api_key = "${UNITYSVC_API_KEY}"

[user.me]
notify_with = ["unitysvc_email", "unitysvc"]
# Daily digest of searches, matches and rejected listings (local time).
digest_at = "08:00"
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


LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def log_level(verbose: bool | None) -> tuple[int, str | None]:
    """The level of the terminal and web UI logs, and a warning for a bad AIMM_LOG_LEVEL.

    ``--verbose`` means DEBUG; otherwise AIMM_LOG_LEVEL (e.g. set in Docker) picks the
    level, and INFO is the default.
    """
    if verbose:
        return logging.DEBUG, None
    name = os.environ.get("AIMM_LOG_LEVEL", "").strip().upper()
    if not name:
        return logging.INFO, None
    if name not in LOG_LEVELS:
        return logging.INFO, (
            f"AIMM_LOG_LEVEL={name} is not one of {', '.join(LOG_LEVELS)}; using INFO."
        )
    return logging.getLevelName(name), None


def setup_logging(
    verbose: bool | None, *, webui: bool, webui_log_retention: int = 2000
) -> tuple[logging.Logger, Any | None]:
    level, level_warning = log_level(verbose)
    log_broadcast_handler = None
    log_handlers: list[logging.Handler] = [
        RichHandler(
            markup=True,
            rich_tracebacks=True,
            show_path=level == logging.DEBUG,
            level=level,
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
        # match the terminal: debug records would otherwise flood the Logs tab
        # and evict useful history from the bounded ring buffer
        log_broadcast_handler.setLevel(level)
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
    if level_warning:
        logger.warning(f"""{hilight("[Logging]", "fail")} {level_warning}""")
    return logger, log_broadcast_handler


def print_webui_banner(info: Any) -> None:
    """Print a prominent panel showing how to reach the web UI."""
    text = Text()
    for url in info.urls:
        text.append("🌐  ", style="bold")
        text.append(url + "\n", style="bold cyan")
    text.append("\n")

    if info.exposed and getattr(info, "proxy_auth", False):
        text.append("No password: your reverse proxy signs users in.\n")
        text.append(f"{info.proxy_check}.\n", style="dim")
        if not info.proxy_verified:
            text.append(
                "\n⚠  Anyone who reaches this port directly gets in: make it reachable only\n"
                "   through the reverse proxy, or set AIMM_WEBUI_PROXY_SECRET.\n",
                style="bold red",
            )
    elif info.exposed:
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
