"""Extract web UI credentials from the config file.

Two modes:

1. ``[marketplace.facebook]`` has ``username`` and ``password`` set →
   the web UI gates access behind those credentials. The user types them
   into the login form and the server compares. This reuses the secret
   the user already needs for Facebook scraping — no new secret to
   manage.

2. Nothing set → **setup mode**. The web UI login form doubles as a
   first-run setup screen. The user enters Facebook credentials which
   the server writes into ``[marketplace.facebook]`` of the config and
   then uses for both the Facebook login and subsequent web UI auth.
   The user can also skip and use the editor without any password
   (loopback only).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - legacy runtimes
    import tomli as tomllib


@dataclass
class ExtractedCredentials:
    username: str | None
    password: str | None


def _parse_toml(config_files: List[Path]) -> Dict[str, Any]:
    """Merge all config files into a single dict. Files that fail to
    parse are skipped silently — we can still extract credentials from
    the files that do parse.
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
    """Return the Facebook marketplace credentials from the config, or
    (None, None) if they are not set. Only ``[marketplace.facebook]`` is
    consulted — other marketplaces are not supported yet.
    """
    merged = _parse_toml(config_files)
    facebook = (merged.get("marketplace") or {}).get("facebook")
    if not isinstance(facebook, dict):
        return ExtractedCredentials(None, None)
    username = facebook.get("username")
    password = facebook.get("password")
    if isinstance(username, str) and isinstance(password, str) and username and password:
        return ExtractedCredentials(username=username, password=password)
    return ExtractedCredentials(None, None)


# ----------------------------------------------------------------------
# Writing credentials back to the config file during setup mode.
# ----------------------------------------------------------------------


_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_ASSIGN_RE = re.compile(
    r"^(?P<indent>\s*)(?P<hash>#?\s*)(?P<key>[A-Za-z0-9_\-]+)\s*=\s*.*$"
)


def set_value_in_section(
    content: str, section: str, key: str, value: str
) -> Tuple[str, bool]:
    """Set ``section.key = value`` in TOML content.

    - If the section exists and has an assignment (commented or not)
      for ``key``, replace that line.
    - If the section exists but has no assignment for ``key``, insert
      a new line immediately after the section header.
    - If the section does not exist, append a new section at the end
      of the file.

    Returns ``(new_content, was_modified)``.
    """
    quoted = f'"{value}"'
    lines = content.splitlines(keepends=True)
    in_section = False
    section_header_index: int | None = None
    replaced = False

    for i, line in enumerate(lines):
        section_match = _SECTION_RE.match(line.rstrip("\r\n"))
        if section_match:
            if in_section and not replaced and section_header_index is not None:
                newline = _detect_newline(content)
                lines.insert(
                    section_header_index + 1, f"{key} = {quoted}{newline}"
                )
                return "".join(lines), True
            in_section = section_match.group(1).strip() == section
            if in_section:
                section_header_index = i
            continue

        if in_section:
            assign_match = _ASSIGN_RE.match(line.rstrip("\r\n"))
            if assign_match and assign_match.group("key") == key:
                newline = line[len(line.rstrip("\r\n")) :]
                lines[i] = f"{assign_match.group('indent')}{key} = {quoted}{newline}"
                replaced = True
                return "".join(lines), True

    if in_section and not replaced and section_header_index is not None:
        newline = _detect_newline(content)
        lines.insert(section_header_index + 1, f"{key} = {quoted}{newline}")
        return "".join(lines), True

    newline = _detect_newline(content)
    suffix = f"{newline}[{section}]{newline}{key} = {quoted}{newline}"
    if content and not content.endswith(("\n", "\r\n")):
        suffix = newline + suffix
    return content + suffix, True


def _detect_newline(content: str) -> str:
    if "\r\n" in content:
        return "\r\n"
    return "\n"
