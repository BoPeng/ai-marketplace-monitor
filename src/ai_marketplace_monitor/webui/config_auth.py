"""Extract web UI credentials from the config file.

Two modes:

1. A ``[marketplace.*]`` section has ``username`` and ``password`` set,
   or the ``FACEBOOK_USERNAME`` / ``FACEBOOK_PASSWORD`` environment
   variables are present → the web UI gates access behind those
   credentials.

2. Nothing set → **open mode**. The web UI runs without authentication
   but only on loopback (127.0.0.1).  ``--webui-host`` is disallowed
   in this mode so the instance can only be accessed locally.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - legacy runtimes
    import tomli as tomllib


@dataclass
class ExtractedCredentials:
    username: str | None
    password: str | None


def _parse_toml(config_files: List[Path]) -> Dict[str, Any]:
    """Merge all config files into a single dict.

    Files that fail to parse are skipped silently — we can still
    extract credentials from the files that do parse.
    """
    merged: Dict[str, Any] = {}
    for path in config_files:
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        _deep_merge(merged, data)
    return merged


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    for key, value in src.items():
        if key in dst and isinstance(dst[key], dict) and isinstance(value, dict):
            _deep_merge(dst[key], value)
        else:
            dst[key] = value


def extract_credentials(config_files: List[Path]) -> ExtractedCredentials:
    """Return marketplace credentials from the config, or (None, None).

    Checks all ``[marketplace.*]`` sections and returns the first one
    that has both ``username`` and ``password`` set.  If nothing is
    found in the config files, falls back to the ``FACEBOOK_USERNAME``
    and ``FACEBOOK_PASSWORD`` environment variables.
    """
    merged = _parse_toml(config_files)
    marketplaces = merged.get("marketplace")
    if isinstance(marketplaces, dict):
        for section in marketplaces.values():
            if not isinstance(section, dict):
                continue
            username = section.get("username")
            password = section.get("password")
            if isinstance(username, str) and isinstance(password, str) and username and password:
                return ExtractedCredentials(username=username, password=password)

    # Fallback: well-known environment variables (Facebook only for now).
    fb_user = os.environ.get("FACEBOOK_USERNAME")
    fb_pass = os.environ.get("FACEBOOK_PASSWORD")
    if fb_user and fb_pass:
        return ExtractedCredentials(username=fb_user, password=fb_pass)

    return ExtractedCredentials(None, None)
