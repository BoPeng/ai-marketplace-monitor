"""The single path that writes chat proposals into config files."""

import os
import shutil
from dataclasses import fields
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

import tomlkit

from ..utils import BaseConfig
from .ai_sections import read_toml
from .messages import Confirm, Say
from .sections import ChatContext, SectionProposal
from .ui import ChatUI

# `request` is written only once the loader accepts it (added by #362)
REQUEST_SUPPORTED = "request" in {f.name for f in fields(BaseConfig)}


class CommitOutcome(Enum):
    WRITTEN = "written"
    DECLINED = "declined"  # the user said no; nothing written
    FAILED = "failed"  # written, but a later file overrides it


def render_section(proposal: SectionProposal) -> str:
    assert proposal.ref.name is not None
    return tomlkit.dumps({proposal.ref.type: {proposal.ref.name: proposal.values}})


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
    if REQUEST_SUPPORTED and request:
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
    if path.exists():
        backup_file(path, ctx.backup_dir)
    write_section(path, ref.type, ref.name, proposal.values, proposal.request)
    if path not in ctx.files:
        ctx.files.insert(0, path)  # only the default file can be new; it is read first

    effective = effective_section(ctx.files, ref.type, ref.name)
    effective.pop("request", None)
    if effective == proposal.values:
        await ui.say(Say(f"Saved [{ref.label()}] to {path}.", kind="success"))
        return CommitOutcome.WRITTEN
    later = ctx.files[ctx.files.index(path) + 1 :]
    overrides = []
    for other in later:
        keys = sorted(read_toml(other).get(ref.type, {}).get(ref.name, {}))
        if keys:
            overrides.append(f"{other} ({', '.join(keys)})")
    await ui.say(
        Say(
            f"Saved to {path}, but [{ref.label()}] is overridden by {'; '.join(overrides)}. "
            "Remove those keys there for this change to take effect.",
            kind="error",
        )
    )
    return CommitOutcome.FAILED
