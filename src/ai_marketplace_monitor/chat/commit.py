"""The single path that writes chat proposals into config files."""

import os
import shutil
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Tuple

import tomlkit
from tomlkit.exceptions import ParseError

from .ai_sections import ConfigReadError, read_toml
from .messages import Confirm, Say
from .sections import ChatContext, SectionProposal
from .ui import ChatUI


class CommitOutcome(Enum):
    WRITTEN = "written"
    DECLINED = "declined"  # the user said no; nothing written
    FAILED = "failed"  # written, but a later file overrides it


def render_section(proposal: SectionProposal) -> str:
    """The section as TOML, exactly as `write_section` will write its keys."""
    assert proposal.ref.name is not None
    values = (
        {"request": proposal.request, **proposal.values} if proposal.request else proposal.values
    )
    return tomlkit.dumps({proposal.ref.type: {proposal.ref.name: values}})


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


def write_section(
    path: Path, section_type: str, name: str, values: Dict[str, Any], request: str | None
) -> None:
    """Add or replace one section, leaving the rest of the file untouched."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    doc = tomlkit.parse(text) if text else tomlkit.document()
    if section_type not in doc:
        doc[section_type] = tomlkit.table(is_super_table=True)
    parent: Any = doc[section_type]
    old = parent.get(name)
    table = tomlkit.table()
    if request:
        table["request"] = request
    elif old is not None and "request" in old:
        table["request"] = old["request"]
    for key, value in values.items():
        table[key] = value
    parent[name] = table
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def effective_section(files: List[Path], section_type: str, name: str) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for path in files:
        merged.update(read_toml(path).get(section_type, {}).get(name, {}))
    return merged


async def commit(ui: ChatUI, proposal: SectionProposal, ctx: ChatContext) -> CommitOutcome:
    """Preview, confirm, back up, write, and verify one proposal."""
    ref, path = proposal.ref, proposal.target_file
    assert ref.name is not None
    await ui.say(Say(f"```toml\n{render_section(proposal)}```", markdown=True))
    if await ui.ask(Confirm(f"Write this to {path}?")) != "yes":
        return CommitOutcome.DECLINED
    try:
        if path.exists():
            backup_file(path, ctx.backup_dir)
        write_section(path, ref.type, ref.name, proposal.values, proposal.request)
        if path not in ctx.files:
            ctx.files.insert(0, path)  # only the default file can be new; it is read first
        conflicts = _conflicts(ctx.files, proposal)
    except (ParseError, OSError, ConfigReadError) as e:
        await ui.say(Say(f"Could not update {path}: {e}", kind="error"))
        return CommitOutcome.FAILED

    if not conflicts:
        await ui.say(Say(f"Saved [{ref.label()}] to {path}.", kind="success"))
        return CommitOutcome.WRITTEN
    detail = "; ".join(f"{other} ({', '.join(keys)})" for other, keys in conflicts)
    await ui.say(
        Say(
            f"Saved to {path}, but [{ref.label()}] is also set in {detail}, which overrides or "
            "adds to it. Remove those keys there for this change to take effect.",
            kind="error",
        )
    )
    return CommitOutcome.FAILED


def _conflicts(files: List[Path], proposal: SectionProposal) -> List[Tuple[Path, List[str]]]:
    """Files whose keys make the effective section differ from the proposal, with those keys.

    Later files override earlier ones, so each mismatched key is attributed to the last file
    (in read order) that defines it.
    """
    ref = proposal.ref
    assert ref.name is not None
    effective = effective_section(files, ref.type, ref.name)
    wanted = proposal.values
    bad = {
        k for k, v in effective.items() if k != "request" and (k not in wanted or wanted[k] != v)
    }
    by_file: Dict[Path, List[str]] = {}
    for key in sorted(bad):
        owner = [f for f in files if key in read_toml(f).get(ref.type, {}).get(ref.name, {})][-1]
        by_file.setdefault(owner, []).append(key)
    return [(f, by_file[f]) for f in files if f in by_file]
