"""Implementation for the `aimm admin` command."""

from pathlib import Path
from typing import List

import typer

from ..config import load_config_dicts
from ..config_toml import dump_config_toml
from ..normalize import expand, normalize
from ..utils import CacheType, amm_home, cache, hilight
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
    if clear_cache == "all":
        cache.clear()
    elif clear_cache in [x.value for x in CacheType]:
        cache.evict(tag=clear_cache)
    else:
        logger.error(
            f"""{hilight("[Clear Cache]", "fail")} {clear_cache} is not a valid cache type. Allowed cache types are {", ".join([x.value for x in CacheType])} and all """
        )
        raise typer.Exit(1)
    logger.info(f"""{hilight("[Clear Cache]", "succ")} Cache cleared.""")
