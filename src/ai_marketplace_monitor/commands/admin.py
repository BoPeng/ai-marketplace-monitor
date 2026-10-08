"""Implementation for the `aimm admin` command."""

from pathlib import Path
from typing import List

import typer

from ..config import Config, load_config_dicts
from ..config_toml import dump_config_toml
from ..normalize import expand, normalize
from ..user import send_test_notifications
from ..utils import amm_home, cache, hilight, is_cache_broken
from ..utils import clear_cache as clear_cache_now
from .common import setup_logging


def config_files_with_default(config_files: List[Path] | None) -> List[Path]:
    default_config = amm_home / "config.toml"
    return ([default_config] if default_config.exists() else []) + [
        path.expanduser().resolve() for path in config_files or []
    ]


def print_normalized_config(config_files: List[Path] | None, *, expanded: bool) -> None:
    system_cfg, user_cfg = load_config_dicts(config_files_with_default(config_files))
    result = expand(user_cfg, system_cfg) if expanded else normalize(user_cfg, system_cfg)
    typer.echo(dump_config_toml(result.config), nl=False)


def run_clear_cache(clear_cache: str, *, verbose: bool | None = False) -> None:
    logger, _ = setup_logging(verbose, webui=False)
    result = clear_cache_now(cache, clear_cache)
    for path in result.removed:
        logger.info(f"""{hilight("[Clear Cache]", "info")} Removed {path}""")
    if not result.ok:
        hint = " Use --clear-cache all." if is_cache_broken(cache) else ""
        logger.error(f"""{hilight("[Clear Cache]", "fail")} {result.message}{hint}""")
        raise typer.Exit(1)
    logger.info(f"""{hilight("[Clear Cache]", "succ")} {result.message}""")


def run_test_notification(
    config_files: List[Path] | None, user: str | None, *, verbose: bool | None = False
) -> None:
    """Send a test message through each channel of each user (or one user); exit 1 on failure."""
    logger, _ = setup_logging(verbose, webui=False)
    try:
        config = Config(config_files_with_default(config_files), logger)
        results = send_test_notifications(config.user, user, logger=logger)
    except Exception as e:  # the config does not load, or there is no such user
        logger.error(f"""{hilight("[Test]", "fail")} {e.args[0] if e.args else e}""")
        raise typer.Exit(1) from e
    failed = not results
    if not results:
        typer.echo("No enabled user to send a test notification to.")
    for name, channels in results.items():
        if not channels:
            failed = True
            typer.echo(f"✗ {name}: no notification channel is set up")
        for channel in channels:
            failed = failed or not channel.ok
            mark = "✓" if channel.ok else "✗"
            typer.echo(
                f"{mark} {name}: {channel.channel}" + ("" if channel.ok else f": {channel.error}")
            )
    if failed:
        raise typer.Exit(1)
