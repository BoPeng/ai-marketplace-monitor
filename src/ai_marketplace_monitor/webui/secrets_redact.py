"""Mask secret values in config file content sent to the web UI.

Why
---
The project stores Facebook login credentials and API tokens as plain
values inside ``config.toml``. Serving that file to a browser unmasked
exposes those secrets to devtools, screen-sharing, browser history, and
anyone who logs into the web UI. We redact sensitive values on the way
out and restore them on the way in, so:

  - The editor never has to show the real secret (unless the user
    explicitly types over the mask to set a new one).
  - The user can save without retyping every secret — the mask literal
    ``"<REDACTED>"`` round-trips back to the original value.
  - Typing a real new value over the mask *does* write it through.

Scope
-----
This is a line-based TOML scanner for common flat assignments like
``password = "..."``. It does NOT support multi-line strings, inline
tables, or arrays of strings — those would need a real TOML parser to
redact safely. If a sensitive key uses one of those shapes, we just
leave it unredacted rather than mis-parse it. Users who need that
should split secrets into a separate file (planned follow-up).
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# The literal we render in place of real secret values.
MASK = "<REDACTED>"

# Key names treated as sensitive. Case-insensitive substring match,
# applied to the TOML key (e.g. ``pushbullet_token`` matches ``token``).
_SENSITIVE_SUBSTRINGS = (
    "password",
    "token",
    "api_key",
    "secret",
)
# Exact-match keys that don't contain one of the substrings above but
# are still sensitive (identifiers that reveal the user's identity).
_SENSITIVE_EXACT = {"username", "api_secret"}

# A simple `section.path = value` line. We only match double- and
# single-quoted scalar string values on the same line. Leading/trailing
# whitespace and trailing comments are tolerated.
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_ASSIGN_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?P<key>[A-Za-z0-9_\-]+)"
    r"(?P<eq>\s*=\s*)"
    r"(?P<quote>[\"'])(?P<value>[^\"'\n]*)(?P=quote)"
    r"(?P<tail>.*)$"
)


SecretMap = Dict[Tuple[str, str], str]


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    if k in _SENSITIVE_EXACT:
        return True
    return any(s in k for s in _SENSITIVE_SUBSTRINGS)


def redact(content: str) -> Tuple[str, SecretMap]:
    """Return (redacted_content, secret_map).

    ``secret_map`` is keyed by ``(section, key)`` so different sections
    with the same key name (e.g. two ``[user.*]`` blocks both having a
    ``pushbullet_token``) don't collide.
    """
    secrets: SecretMap = {}
    out: List[str] = []
    section = ""
    for line in content.splitlines(keepends=True):
        section_match = _SECTION_RE.match(line.rstrip("\r\n"))
        if section_match:
            section = section_match.group(1).strip()
            out.append(line)
            continue

        assign_match = _ASSIGN_RE.match(line.rstrip("\r\n"))
        if assign_match:
            key = assign_match.group("key")
            if _is_sensitive(key):
                value = assign_match.group("value")
                if value and value != MASK:
                    secrets[(section, key)] = value
                    quote = assign_match.group("quote")
                    tail = assign_match.group("tail")
                    newline = line[len(line.rstrip("\r\n")) :]
                    line = (
                        f"{assign_match.group('indent')}{key}"
                        f"{assign_match.group('eq')}{quote}{MASK}{quote}{tail}{newline}"
                    )
        out.append(line)
    return "".join(out), secrets


def restore(content: str, secrets: SecretMap) -> str:
    """Restore redacted masks to their real values.

    Unknown masks and non-sensitive keys pass through unchanged.
    """
    if not secrets:
        return content
    out: List[str] = []
    section = ""
    for line in content.splitlines(keepends=True):
        section_match = _SECTION_RE.match(line.rstrip("\r\n"))
        if section_match:
            section = section_match.group(1).strip()
            out.append(line)
            continue

        assign_match = _ASSIGN_RE.match(line.rstrip("\r\n"))
        if assign_match and assign_match.group("value") == MASK:
            key = assign_match.group("key")
            real = secrets.get((section, key))
            if real is not None:
                quote = assign_match.group("quote")
                tail = assign_match.group("tail")
                newline = line[len(line.rstrip("\r\n")) :]
                line = (
                    f"{assign_match.group('indent')}{key}"
                    f"{assign_match.group('eq')}{quote}{real}{quote}{tail}{newline}"
                )
        out.append(line)
    return "".join(out)


def has_mask(content: str) -> bool:
    return f'"{MASK}"' in content or f"'{MASK}'" in content
