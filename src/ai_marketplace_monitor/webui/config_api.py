"""Config file read/write/validate helpers for the web UI."""

from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from ..config import Config
from .secrets_redact import SecretMap, redact, restore


@dataclass
class ConfigFileInfo:
    id: str
    path: str
    name: str
    mtime: float
    size: int


@dataclass
class SectionInfo:
    """A TOML section header found by a line-by-line scan.

    Line numbers are 0-based. `line_end` is exclusive — it points at
    the next section header, or at the total line count if this is the
    last section. ``fields`` is a best-effort ``tomllib``-parsed dict of
    the section's key→value pairs (empty if the file has a syntax error).
    """

    name: str  # e.g. "marketplace.facebook"
    prefix: str  # e.g. "marketplace"
    suffix: str  # e.g. "facebook" — empty if the section has no dot (e.g. "monitor")
    line_start: int  # line containing the [header]
    line_end: int  # exclusive upper bound
    fields: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.fields is None:
            self.fields = {}


_SECTION_HEADER_RE = re.compile(r"^\s*\[([^\]\n]+)\]\s*$")


def _parse_fields(content: str) -> Dict[str, Dict[str, Any]]:
    """Parse the TOML content via tomllib and return a flat mapping of
    dotted-section-names to {key: value} dicts.

    Best-effort: if parsing fails (malformed TOML mid-edit), returns {}.
    """
    try:
        data = tomllib.loads(content)
    except Exception:
        return {}

    result: Dict[str, Dict[str, Any]] = {}

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            # Decide if this dict is a "section" (has at least one non-dict
            # leaf) or purely nested dicts (like `[marketplace]` containing
            # `[marketplace.facebook]`).
            leaves = {k: v for k, v in node.items() if not isinstance(v, dict)}
            if leaves:
                result[prefix] = leaves
            for k, v in node.items():
                if isinstance(v, dict):
                    walk(f"{prefix}.{k}" if prefix else k, v)

    walk("", data)
    return result


def scan_sections(content: str) -> List[SectionInfo]:
    """Find every ``[section.name]`` header in ``content``.

    Returns a list of ``SectionInfo`` in file order. Line-based scan —
    no TOML parsing, works even on malformed files (e.g. during an
    in-progress edit). Each section is enriched with parsed ``fields``
    from a best-effort ``tomllib.loads()`` pass.
    """
    lines = content.splitlines()
    headers: List[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _SECTION_HEADER_RE.match(line)
        if m:
            headers.append((i, m.group(1).strip()))

    parsed = _parse_fields(content)

    sections: List[SectionInfo] = []
    for idx, (line_start, name) in enumerate(headers):
        line_end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        dot = name.find(".")
        sections.append(
            SectionInfo(
                name=name,
                prefix=name[:dot] if dot >= 0 else name,
                suffix=name[dot + 1 :] if dot >= 0 else "",
                line_start=line_start,
                line_end=line_end,
                fields=parsed.get(name, {}),
            )
        )
    return sections


class ConfigFileService:
    """Read/write/validate for a single editable config file.

    Designed with a list-shaped API even though only one file is editable
    today, so multi-file support can be added without changing the HTTP
    contract.
    """

    def __init__(self, config_files: List[Path], logger: logging.Logger | None = None) -> None:
        if not config_files:
            raise ValueError("At least one config file is required.")
        self._editable: Path = config_files[-1].expanduser().resolve()
        self._all: List[Path] = [p.expanduser().resolve() for p in config_files]
        self._logger = logger
        # Most recent secret map, populated on every read() call. Write()
        # uses this to round-trip "<REDACTED>" masks back to real values.
        self._secrets: SecretMap = {}

    @property
    def editable_path(self) -> Path:
        return self._editable

    def list_files(self) -> List[ConfigFileInfo]:
        stat = self._editable.stat()
        return [
            ConfigFileInfo(
                id="primary",
                path=str(self._editable),
                name=self._editable.name,
                mtime=stat.st_mtime,
                size=stat.st_size,
            )
        ]

    def read(self, file_id: str) -> Tuple[str, float]:
        self._require(file_id)
        raw = self._editable.read_text(encoding="utf-8")
        redacted, secrets = redact(raw)
        self._secrets = secrets
        return redacted, self._editable.stat().st_mtime

    def validate(self, content: str) -> Tuple[bool, str | None]:
        """Parse the given content using the real Config loader.

        Masks in ``content`` are first restored to their real values so we
        validate what will actually be written.
        """
        restored = restore(content, self._secrets)
        tmp_dir = self._editable.parent
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(tmp_dir),
            prefix=f".{self._editable.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            tmp.write(restored)
            tmp.flush()
            tmp.close()
            tmp_path = Path(tmp.name)
            files = [tmp_path if p == self._editable else p for p in self._all]
            try:
                Config(files, self._logger)
                return True, None
            except Exception as e:
                return False, str(e)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def write(
        self, file_id: str, content: str, base_mtime: float | None
    ) -> Tuple[float, bool, str | None]:
        """Validate and atomically write the file.

        Returns (new_mtime, ok, error_message).
        """
        self._require(file_id)

        if base_mtime is not None:
            current = self._editable.stat().st_mtime
            # Allow a tiny epsilon for filesystems with coarse mtimes.
            if abs(current - base_mtime) > 0.001:
                return current, False, "conflict: file changed on disk"

        # Restore masks before validating and writing so round-tripped
        # "<REDACTED>" tokens become the real secret values on disk.
        restored = restore(content, self._secrets)

        ok, error = self.validate(restored)
        if not ok:
            return (
                self._editable.stat().st_mtime,
                False,
                error or "unknown validation error",
            )

        # Atomic write: temp file in same dir + os.replace.
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self._editable.parent),
            prefix=f".{self._editable.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            tmp.write(restored)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, self._editable)
        except Exception as e:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            return self._editable.stat().st_mtime, False, str(e)

        # Refresh secret map from the new on-disk contents so any future
        # read() uses the latest secrets (e.g. user typed a new password).
        try:
            _, self._secrets = redact(
                self._editable.read_text(encoding="utf-8")
            )
        except OSError:
            pass

        return self._editable.stat().st_mtime, True, None

    def _require(self, file_id: str) -> None:
        if file_id != "primary":
            raise KeyError(f"Unknown config file id: {file_id}")
