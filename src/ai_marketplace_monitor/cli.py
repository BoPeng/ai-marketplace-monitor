"""Public command-line interface for ai-marketplace-monitor."""

from pathlib import Path
from typing import Annotated, List, Optional

import typer

from . import __version__
from .commands.admin import (
    print_normalized_config as _print_normalized_config,
)
from .commands.admin import (
    run_clear_cache as _run_clear_cache,
)
from .commands.admin import (
    run_test_notification as _run_test_notification,
)
from .commands.check import run_check as _run_check
from .commands.run import run_monitor as _run_monitor
from .utils import CacheType

app = typer.Typer(help="AI Marketplace Monitor commands.", invoke_without_command=True)


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


@app.callback()
def root(
    ctx: typer.Context,
    config_files: Annotated[
        List[Path] | None,
        typer.Option(
            "-r",
            "--config",
            "--config-file",
            help="Path to one or more configuration files in TOML format. `~/.ai-marketplace-monitor/config.toml will always be read.",
        ),
    ] = None,
    verbose: Annotated[
        Optional[bool],
        typer.Option("--verbose", "-v", help="If set to true, will show debug messages."),
    ] = False,
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
    """AI Marketplace Monitor command group."""
    if ctx.invoked_subcommand is None:
        _run_monitor(
            config_files,
            verbose,
            webui,
            webui_host,
            webui_port,
            webui_log_retention,
        )


@app.command("run")
def run(
    config_files: Annotated[
        List[Path] | None,
        typer.Option(
            "-r",
            "--config",
            "--config-file",
            help="Path to one or more configuration files in TOML format. `~/.ai-marketplace-monitor/config.toml will always be read.",
        ),
    ] = None,
    verbose: Annotated[
        Optional[bool],
        typer.Option("--verbose", "-v", help="If set to true, will show debug messages."),
    ] = False,
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
    """Run the long-lived marketplace monitor loop."""
    _run_monitor(
        config_files,
        verbose,
        webui,
        webui_host,
        webui_port,
        webui_log_retention,
    )


@app.command("check")
def check(
    items: Annotated[
        List[str],
        typer.Argument(
            help="One or more cached item ids or listing URLs to check against your config."
        ),
    ],
    config_files: Annotated[
        List[Path] | None,
        typer.Option(
            "-r",
            "--config",
            "--config-file",
            help="Path to one or more configuration files in TOML format. `~/.ai-marketplace-monitor/config.toml will always be read.",
        ),
    ] = None,
    verbose: Annotated[
        Optional[bool],
        typer.Option("--verbose", "-v", help="If set to true, will show debug messages."),
    ] = False,
    for_item: Annotated[
        Optional[str],
        typer.Option(
            "--for",
            help="Item to check for the supplied URLs. You will be prompted if unspecified and there are multiple items to search.",
        ),
    ] = None,
) -> None:
    """Check one or more listings once, then exit."""
    _run_check(config_files, verbose, items, for_item)


@app.command("admin")
def admin(
    config_files: Annotated[
        List[Path] | None,
        typer.Option(
            "-r",
            "--config",
            "--config-file",
            help="Path to one or more configuration files in TOML format. `~/.ai-marketplace-monitor/config.toml will always be read.",
        ),
    ] = None,
    clear_cache: Annotated[
        Optional[str],
        typer.Option(
            "--clear-cache",
            help=(
                "Remove all or selected category of cached items and treat all queries as new. "
                f"""Allowed cache types are {", ".join([x.value for x in CacheType])} and all."""
            ),
        ),
    ] = None,
    test_notification: Annotated[
        bool,
        typer.Option(
            "--test-notification",
            help=(
                "Send a test message through every notification channel of every enabled user, "
                "or of USER, and report which channels work. Nothing is recorded in the cache."
            ),
        ),
    ] = False,
    user: Annotated[
        Optional[str],
        typer.Argument(help="With --test-notification: the user to test (default: all users)."),
    ] = None,
    normalize_config: Annotated[
        bool,
        typer.Option(
            "--normalize-config",
            "--normalize",
            help="Print compact normalized config to stdout and exit without writing files.",
        ),
    ] = False,
    expand_config: Annotated[
        bool,
        typer.Option(
            "--expand-config",
            "--expand",
            help="Print expanded config to stdout and exit without writing files.",
        ),
    ] = False,
    verbose: Annotated[
        Optional[bool],
        typer.Option("--verbose", "-v", help="If set to true, will show debug messages."),
    ] = False,
) -> None:
    """Run one-shot local administration tasks, then exit."""
    actions = sum([clear_cache is not None, test_notification, normalize_config, expand_config])
    if actions != 1:
        typer.echo(
            "Choose exactly one of --clear-cache, --test-notification, --normalize-config, and "
            "--expand-config.",
            err=True,
        )
        raise typer.Exit(1)
    if user is not None and not test_notification:
        typer.echo(
            f"Unexpected argument {user}: a user is given with --test-notification.", err=True
        )
        raise typer.Exit(1)
    if clear_cache is not None:
        _run_clear_cache(clear_cache, verbose=verbose)
        return
    if test_notification:
        _run_test_notification(config_files, user, verbose=verbose)
        return
    try:
        _print_normalized_config(config_files, expanded=expand_config)
    except Exception as e:
        typer.echo(f"Config normalization failed: {e}", err=True)
        raise typer.Exit(1) from e


@app.command("configure")
def configure(
    section: Annotated[
        Optional[str],
        typer.Argument(
            help=(
                "Optional section to configure, e.g. 'ai', 'ai.<name>', 'marketplace', "
                "'item.<name>', 'notification', 'user.<name>', 'region', 'translation', "
                "or 'monitor'."
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
    from .configure.cli import run_configure_cli

    run_configure_cli(section, config_files)


if __name__ == "__main__":
    app()  # pragma: no cover
