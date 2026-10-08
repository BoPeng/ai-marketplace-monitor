"""Implementation for the `aimm admin` command."""

import sqlite3
from pathlib import Path
from typing import List

import typer

from ..config import load_config_dicts
from ..config_toml import dump_config_toml
from ..normalize import expand, normalize
from ..utils import (
    CacheCorruptedError,
    CacheType,
    amm_home,
    cache,
    hilight,
    is_cache_broken,
    remove_cache_files,
)
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
        try:
            if is_cache_broken(cache):
                raise CacheCorruptedError(str(cache.error))  # type: ignore[attr-defined]
            cache.clear()
        except (CacheCorruptedError, sqlite3.DatabaseError) as e:
            # a corrupted database cannot be cleared from inside: remove its files
            cache.close()
            directory = Path(cache.directory)
            for path in remove_cache_files(directory):
                logger.info(f"""{hilight("[Clear Cache]", "info")} Removed {path}""")
            logger.info(
                f"""{hilight("[Clear Cache]", "succ")} The cache could not be read ({e}), so its """
                f"files were removed. aimm starts with an empty cache."
            )
            return
    elif clear_cache in [x.value for x in CacheType]:
        if is_cache_broken(cache):
            logger.error(
                f"""{hilight("[Clear Cache]", "fail")} The cache cannot be read, so it cannot be """
                "cleared in part. Use --clear-cache all."
            )
            raise typer.Exit(1)
        cache.evict(tag=clear_cache)
    else:
        logger.error(
            f"""{hilight("[Clear Cache]", "fail")} {clear_cache} is not a valid cache type. Allowed cache types are {", ".join([x.value for x in CacheType])} and all """
        )
        raise typer.Exit(1)
    logger.info(f"""{hilight("[Clear Cache]", "succ")} Cache cleared.""")
