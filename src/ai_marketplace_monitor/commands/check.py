"""Implementation for the `aimm check` command."""

from pathlib import Path
from typing import List

from ..utils import hilight
from .common import require_readable_cache, setup_logging


def run_check(
    config_files: List[Path] | None,
    headless: bool | None,
    verbose: bool | None,
    items: List[str],
    for_item: str | None,
) -> None:
    logger, _ = setup_logging(verbose, webui=False)
    require_readable_cache(logger)
    from ..monitor import MarketplaceMonitor

    monitor = None
    try:
        monitor = MarketplaceMonitor(config_files, headless, logger)
        monitor.check_items(items, for_item)
    except Exception as e:
        logger.error(f"""{hilight("[Check]", "fail")} {e}""")
        raise
    finally:
        if monitor is not None:
            monitor.stop_monitor()
