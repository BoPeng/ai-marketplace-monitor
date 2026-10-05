"""The write path for interactive configuration: preview, confirm, back up, write, verify."""

from __future__ import annotations

import difflib
import os
import re
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
from .toolkits import SINGLETONS, section_label
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
    out = {
        (section_type, name): section
        for section_type, body in cfg.items()
        if section_type not in SINGLETONS and isinstance(body, dict)
        for name, section in body.items()
    }
    for section_type in SINGLETONS:  # one unnamed section, keyed (type, type)
        if isinstance(cfg.get(section_type), dict):
            out[(section_type, section_type)] = cfg[section_type]
    return out


def _owner(files: List[Path], key: SectionKey) -> Path | None:
    """The last file that defines a section (later files win when merged)."""
    owner = None
    for path in files:
        content = read_toml(path)
        if (key[0] in SINGLETONS and key[0] in content) or key[1] in content.get(key[0], {}):
            owner = path
    return owner


def _first_owner(files: List[Path], section_type: str) -> Path | None:
    """The file that defines the first section of a type (merged order is first appearance)."""
    return next((path for path in files if read_toml(path).get(section_type)), None)


def _edit_documents(
    files: List[Path],
    changes: Dict[SectionKey, Dict[str, Any]],
    default: Path,
    first: List[SectionKey] = (),  # type: ignore[assignment]
) -> Dict[Path, str]:
    """New text of each file that holds a changed section, edited key by key in place.

    Comments, key order and every other section of the file are kept. A section in ``first``
    is placed before the others of its type, in the file holding the current first one (and
    removed from any other file).
    """
    docs: Dict[Path, Any] = {}
    moves: Dict[Path, List[Tuple[str, str, Any]]] = {}

    def doc_of(path: Path) -> Any:
        if path not in docs:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            docs[path] = tomlkit.parse(text) if text else tomlkit.document()
        return docs[path]

    for key, values in changes.items():
        owner = _owner(files, key)
        path = owner or default
        if key in first:
            path = _first_owner(files, key[0]) or path
            for other in files:
                if other != path and key[1] in read_toml(other).get(key[0], {}):
                    del doc_of(other)[key[0]][key[1]]
        doc = doc_of(path)
        section_type, name = key
        parent: Any = doc  # a singleton is a table of the document itself
        if section_type not in SINGLETONS:
            if section_type not in doc:
                doc[section_type] = tomlkit.table(is_super_table=True)
            parent = doc[section_type]
        created = name not in parent
        if created:
            parent[name] = tomlkit.table()
        table = parent[name]
        for k in [k for k in table if k not in values]:
            del table[k]
        for k, v in values.items():
            if k not in table or table[k] != v:
                table[k] = v
        if created:
            table.add(tomlkit.nl())  # a blank line before whatever table follows
        if key in first:
            moves.setdefault(path, []).append((section_type, name, table))
            del parent[name]
    texts = {path: tomlkit.dumps(doc) for path, doc in docs.items()}
    for path, sections in moves.items():
        for section_type, name, table in reversed(sections):
            texts[path] = _insert_first(texts[path], section_type, name, table)
    return texts


def _insert_first(text: str, section_type: str, name: str, table: Any) -> str:
    """Insert a section before the first table of its type (they may be spread out)."""
    doc = tomlkit.document()
    parent: Any = tomlkit.table(is_super_table=True)
    parent[name] = table
    doc[section_type] = parent
    rendered = tomlkit.dumps(doc).strip("\n") + "\n\n"
    header = re.compile(rf"^\[\s*{re.escape(section_type)}\s*[.\]]", re.MULTILINE)
    match = header.search(text)
    if match is None:
        return text.rstrip("\n") + ("\n\n" if text.strip() else "") + rendered
    return text[: match.start()] + rendered + text[match.start() :]


async def commit_sections(
    ui: SetupUI,
    new_user_cfg: Dict[str, Any],
    old_user_cfg: Dict[str, Any],
    files: List[Path],
    backup_dir: Path,
    default_file: Path | None = None,
    only: List[SectionKey] | None = None,
    first: List[SectionKey] | None = None,
) -> CommitOutcome:
    """Write the sections that differ between two user configs; leave everything else alone.

    ``only`` limits the write to those sections: any other difference is refused, so a
    section builder can never change another part of the config.

    Each changed section is edited in place in the file that defines it (a new section goes
    to ``default_file``, else the last config file). Preview, confirm, back up, write, verify.
    """
    old, new = _sections(old_user_cfg), _sections(new_user_cfg)
    changes = {key: values for key, values in new.items() if old.get(key) != values}
    first = first or []
    for key in first:  # moving a section first is a change even when its values are not
        if key in new and next(iter(old_user_cfg.get(key[0], {})), None) != key[1]:
            changes.setdefault(key, new[key])
    removed = [key for key in old if key not in new]
    outside = [k for k in [*changes, *removed] if only is not None and k not in only]
    if outside:
        await ui.say(
            "Refusing to write: the change would also modify "
            + ", ".join(section_label(t, n) for t, n in outside)
            + ".",
            kind="error",
        )
        return CommitOutcome.FAILED
    target = default_file or (files[-1] if files else None)
    if not changes:
        await ui.say("Nothing changed; your config is left as it is.", kind="success")
        return CommitOutcome.WRITTEN
    if target is None:
        await ui.say("No config file to write to.", kind="error")
        return CommitOutcome.FAILED
    try:
        plans = _edit_documents(files, changes, target, first)
    except (ParseError, OSError, ConfigReadError) as e:
        await ui.say(f"Could not prepare the change: {e}", kind="error")
        return CommitOutcome.FAILED

    originals = {
        path: path.read_text(encoding="utf-8") if path.exists() else None for path in plans
    }
    for path, text in plans.items():
        before = originals[path] or ""
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=f"{path} (current)",
                tofile=f"{path} (new)",
            )
        )
        await ui.say(f"```diff\n{diff}```", markdown=True)
    if not await ui.confirm("Write these changes?"):
        return CommitOutcome.DECLINED
    # the files may have changed while the user was reading the preview
    changed = [
        str(path)
        for path, text in originals.items()
        if (path.read_text(encoding="utf-8") if path.exists() else None) != text
    ]
    if changed:
        await ui.say(
            f"Not written: {', '.join(changed)} changed while you were reviewing; "
            "please try again.",
            kind="error",
        )
        return CommitOutcome.FAILED

    try:
        for path, text in plans.items():
            if path.exists():
                backup_file(path, backup_dir)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        read_order = files if target in files else [*files, target]
        _, reloaded_cfg = load_config_dicts(read_order)
    except (OSError, ValueError) as e:
        await ui.say(f"Could not update the config: {e}", kind="error")
        return CommitOutcome.FAILED
    reloaded = _sections(reloaded_cfg)
    wrong = [
        section_label(t, n) for (t, n), values in changes.items() if reloaded.get((t, n)) != values
    ]
    wrong += [
        f"[{t}.{n}] (not first)"
        for t, n in first
        if next(iter(reloaded_cfg.get(t, {})), None) != n
    ]
    if wrong:
        await ui.say(
            f"Saved, but {', '.join(wrong)} does not read back as written; another config "
            "file may set some of its keys.",
            kind="error",
        )
        return CommitOutcome.FAILED
    await ui.say(f"Saved {', '.join(str(p) for p in plans)}.", kind="success")
    return CommitOutcome.WRITTEN
