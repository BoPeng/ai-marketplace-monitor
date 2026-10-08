"""Implementation for the `aimm run` command."""

from pathlib import Path
from typing import List

import rich
import typer

from ..utils import amm_home, counter, hilight
from .common import (
    print_webui_banner,
    require_readable_cache,
    seed_default_config,
    setup_logging,
)


def run_monitor(
    config_files: List[Path] | None,
    verbose: bool | None,
    webui: bool,
    webui_host: str,
    webui_port: int,
    webui_log_retention: int,
) -> None:
    logger, log_broadcast_handler = setup_logging(
        verbose, webui=webui, webui_log_retention=webui_log_retention
    )
    require_readable_cache(logger)
    from ..monitor import MarketplaceMonitor

    monitor = None  # type: ignore[assignment]
    webui_server = None
    try:
        # If web UI is on and there are no existing config files, seed
        # the default ~/.ai-marketplace-monitor/config.toml with a
        # template so the user can edit it from the browser on first run.
        if webui and not config_files and not (amm_home / "config.toml").exists():
            seed_default_config(amm_home / "config.toml", logger)

        monitor = MarketplaceMonitor(config_files, logger)
        if webui and log_broadcast_handler is not None:
            from ..webui.server import WebUIConfig, start_webui

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
                    print_webui_banner(webui_info)
                except Exception as e:
                    logger.error(f"""{hilight("[WebUI]", "fail")} Failed to start web UI: {e}""")
        monitor.start_monitor()
    except KeyboardInterrupt:
        rich.print("Exiting...")
        raise typer.Exit() from None
    except Exception as e:
        logger.error(f"""{hilight("[Monitor]", "fail")} {e}""")
        raise
    finally:
        if webui_server is not None:
            webui_server.stop()
        if monitor is not None:
            monitor.stop_monitor()
        rich.print(counter)
