"""The write path for interactive configuration: preview, confirm, back up, write, verify."""

from __future__ import annotations

import difflib
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Tuple

import tomlkit
from tomlkit.exceptions import ParseError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ..config import load_config_dicts
from ..config_toml import dump_config_toml
from ..normalize import NormalizeError, normalize
from .ui import SetupUI


class ConfigReadError(Exception):
    """A config file could not be read or parsed."""

    def __init__(self: "ConfigReadError", path: Path, message: str) -> None:
        super().__init__(f"Cannot read {path}: {message}")
        self.path = path


class CommitOutcome(Enum):
    WRITTEN = "written"
    DECLINED = "declined"  # the user said no; nothing written
    FAILED = "failed"  # not written, or written but overridden by another file


@dataclass
class SectionWrite:
    """One section to add or replace, e.g. ``[ai.unitysvc]`` in ``target_file``."""

    section_type: str
    name: str
    values: Dict[str, Any]
    request: str | None
    target_file: Path
    first: bool = False  # place the section before the others of its type

    @property
    def label(self: "SectionWrite") -> str:
        return f"[{self.section_type}.{self.name}]"


def read_toml(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "rb") as file:
            return tomllib.load(file)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigReadError(path, str(e)) from e


def render_section(write: SectionWrite) -> str:
    """The section as TOML, exactly as ``write_section`` writes its keys."""
    values = {"request": write.request, **write.values} if write.request else write.values
    return tomlkit.dumps({write.section_type: {write.name: values}})


def backup_file(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{path.name}.{datetime.now():%Y%m%d-%H%M%S}"
    dest = backup_dir / stem
    counter = 1
    while dest.exists():
        counter += 1
        dest = backup_dir / f"{stem}-{counter}"
    shutil.copy2(path, dest)
    os.chmod(dest, 0o600)
    return dest


def write_section(write: SectionWrite) -> None:
    """Add or replace one section, preserving the rest of the file."""
    path = write.target_file
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    doc = tomlkit.parse(text) if text else tomlkit.document()
    if write.section_type not in doc:
        doc[write.section_type] = tomlkit.table(is_super_table=True)
    parent: Any = doc[write.section_type]
    old = parent.get(write.name)
    table = tomlkit.table()
    if write.request:
        table["request"] = write.request
    elif old is not None and "request" in old:
        table["request"] = old["request"]
    for key, value in write.values.items():
        table[key] = value
    parent[write.name] = table
    if write.first:
        _put_first(path, parent, write.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _put_first(path: Path, parent: Any, name: str) -> None:
    """Reorder the tables of a section type so that ``name`` comes first."""
    try:
        tables = {key: parent[key] for key in list(parent.keys())}
        for key in tables:
            del parent[key]
        for key in [name, *(k for k in tables if k != name)]:
            parent[key] = tables[key]
    except Exception as e:  # e.g. tables of this type scattered through the file
        raise ConfigReadError(path, f"cannot move [{name}] to the top automatically ({e})") from e


def remove_section(path: Path, section_type: str, name: str) -> None:
    """Delete one section from a file, preserving the rest."""
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    parent: Any = doc.get(section_type)
    if parent is not None and name in parent:
        del parent[name]
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def section_conflicts(files: List[Path], write: SectionWrite) -> List[Tuple[Path, List[str]]]:
    """Keys whose effective value differs from ``write.values``, grouped by the file that sets them.

    Files are merged in read order (later wins); each mismatched key is attributed to the
    last file that defines it. Every file is parsed once.
    """
    tables = [
        (path, read_toml(path).get(write.section_type, {}).get(write.name, {})) for path in files
    ]
    effective: Dict[str, Any] = {}
    owner: Dict[str, Path] = {}
    for path, table in tables:
        for key, value in table.items():
            effective[key] = value
            owner[key] = path
    bad = sorted(
        key
        for key, value in effective.items()
        if key != "request" and (key not in write.values or write.values[key] != value)
    )
    by_file: Dict[Path, List[str]] = {}
    for key in bad:
        by_file.setdefault(owner[key], []).append(key)
    return [(path, by_file[path]) for path in files if path in by_file]


async def commit_section(
    ui: SetupUI, write: SectionWrite, files: List[Path], backup_dir: Path
) -> CommitOutcome:
    """Preview, confirm, back up, write, and verify one section.

    ``files`` is the config read order; a newly created target file is inserted first.
    """
    await ui.say(f"```toml\n{render_section(write)}```", markdown=True)
    if not await ui.confirm(f"Write this to {write.target_file}?"):
        return CommitOutcome.DECLINED
    try:
        if write.target_file.exists():
            backup_file(write.target_file, backup_dir)
        write_section(write)
        if write.target_file not in files:
            files.insert(0, write.target_file)
        conflicts = section_conflicts(files, write)
    except (ParseError, OSError, ConfigReadError) as e:
        await ui.say(f"Could not update {write.target_file}: {e}", kind="error")
        return CommitOutcome.FAILED

    if not conflicts:
        await ui.say(f"Saved {write.label} to {write.target_file}.", kind="success")
        return CommitOutcome.WRITTEN
    detail = "; ".join(f"{other} ({', '.join(keys)})" for other, keys in conflicts)
    await ui.say(
        f"Saved to {write.target_file}, but {write.label} is also set in {detail}, which "
        "overrides or adds to it. Remove those keys there for this change to take effect.",
        kind="error",
    )
    return CommitOutcome.FAILED


SectionKey = Tuple[str, str]


def _sections(cfg: Dict[str, Any]) -> Dict[SectionKey, Dict[str, Any]]:
    out: Dict[SectionKey, Dict[str, Any]] = {}
    for section_type, body in cfg.items():
        if section_type == "monitor":
            out[("monitor", "")] = body
        else:
            out.update({(section_type, name): section for name, section in body.items()})
    return out


def _owner(files: List[Path], key: SectionKey) -> Path | None:
    """The last file that defines a section (later files win when merged)."""
    owner = None
    for path in files:
        data = read_toml(path)
        if (key[0] == "monitor" and "monitor" in data) or key[1] in data.get(key[0], {}):
            owner = path
    return owner


def _section_writes(
    files: List[Path], old: Dict[str, Any], new: Dict[str, Any], default: Path
) -> Dict[Path, str]:
    """New text of each file that holds a changed section (used with several config files)."""
    old_sections, new_sections = _sections(old), _sections(new)
    docs: Dict[Path, Any] = {}
    for key in [*new_sections, *(k for k in old_sections if k not in new_sections)]:
        if old_sections.get(key) == new_sections.get(key):
            continue
        path = _owner(files, key) or default
        if path not in docs:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            docs[path] = tomlkit.parse(text) if text else tomlkit.document()
        doc = docs[path]
        section_type, name = key
        if section_type == "monitor":
            doc["monitor"] = new_sections.get(key, {})
            continue
        if section_type not in doc:
            doc[section_type] = tomlkit.table(is_super_table=True)
        if key in new_sections:
            table = tomlkit.table()
            for k, v in new_sections[key].items():
                table[k] = v
            doc[section_type][name] = table
        elif name in doc[section_type]:
            del doc[section_type][name]
    return {path: tomlkit.dumps(doc) for path, doc in docs.items()}


async def commit_config(
    ui: SetupUI,
    new_expanded: Dict[str, Any],
    files: List[Path],
    system_cfg: Dict[str, Any],
    user_cfg: Dict[str, Any],
    backup_dir: Path,
    default_file: Path | None = None,
) -> CommitOutcome:
    """Normalize an edited (expanded) config, preview, confirm, back up, write, and verify.

    With one config file, the file is rewritten in normalized form. With several, each changed
    section is written into the file that defines it (new sections go to the last file).
    """
    try:
        new = normalize(new_expanded, system_cfg, partial=True).config
        old = normalize(user_cfg, system_cfg, partial=True).config
    except NormalizeError as e:
        await ui.say(f"The new configuration is not valid: {e}", kind="error")
        return CommitOutcome.FAILED
    target = default_file or (files[-1] if files else None)
    if target is None:
        await ui.say("No config file to write to.", kind="error")
        return CommitOutcome.FAILED
    if len(files) <= 1:
        plans = {target: dump_config_toml(new)}
    else:
        plans = _section_writes(files, old, new, target)

    previews = []
    for path, text in plans.items():
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        if before == text:
            continue
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=f"{path} (current)",
                tofile=f"{path} (new)",
            )
        )
        previews.append((path, diff, len(files) <= 1 and "#" in before))
    if not previews:
        await ui.say("Nothing to change in the config files.", kind="success")
        return CommitOutcome.WRITTEN
    for path, diff, has_comments in previews:
        await ui.say(f"```diff\n{diff}```", markdown=True)
        if has_comments:
            await ui.say(
                f"{path} is rewritten in normalized form, so its comments are dropped "
                "(the backup keeps them).",
                kind="warning",
            )
    if not await ui.confirm("Write these changes?"):
        return CommitOutcome.DECLINED

    written: List[Path] = []
    try:
        for path, _diff, _ in previews:
            if path.exists():
                backup_file(path, backup_dir)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(plans[path], encoding="utf-8")
            written.append(path)
        read_order = files if target in files else [*files, target]
        system, user = load_config_dicts(read_order)
        reloaded = normalize(user, system, partial=True).config
    except (OSError, ValueError, NormalizeError) as e:
        await ui.say(f"Could not update the config: {e}", kind="error")
        return CommitOutcome.FAILED
    if reloaded != new:
        changed = sorted(
            f"[{t}.{n}]" if n else f"[{t}]"
            for (t, n), v in _sections(new).items()
            if _sections(reloaded).get((t, n)) != v
        )
        await ui.say(
            f"Saved, but {', '.join(changed) or 'the config'} does not read back as written; "
            "another config file may override it.",
            kind="error",
        )
        return CommitOutcome.FAILED
    await ui.say(f"Saved {', '.join(str(p) for p in written)}.", kind="success")
    return CommitOutcome.WRITTEN
