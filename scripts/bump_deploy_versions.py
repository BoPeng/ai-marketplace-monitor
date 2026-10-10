#!/usr/bin/env python3
"""Pin the app-store templates in deploy/ to a released aimm image.

The docker workflow runs this after it pushes the image of a release tag, with the version
and the image's index digest, then commits the result (see CLAUDE.md). It edits only the
templates that pin a version; running it again for the same version changes nothing.

Usage: python scripts/bump_deploy_versions.py X.Y.Z sha256:<digest>
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_deploy_versions import IMAGE, ROOT

_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PIN = re.escape(IMAGE) + r":\d+\.\d+\.\d+(?:@sha256:[0-9a-f]{64})?"
RELEASES = "https://github.com/BoPeng/ai-marketplace-monitor/releases/tag"


def _sub(pattern: str, repl: str | Callable[[re.Match], str], text: str, file: str) -> str:
    new, count = re.subn(pattern, repl, text, flags=re.MULTILINE | re.DOTALL)
    if count == 0:
        raise ValueError(f"{file}: cannot find {pattern!r}")
    return new


def bump(version: str, digest: str, root: Path = ROOT) -> List[str]:
    """Pin the templates to `version` (and `digest` where required); the files changed."""
    if not _VERSION.match(version):
        raise ValueError(f"not a release version: {version}")
    if not _DIGEST.match(digest):
        raise ValueError(f"not an image digest: {digest}")
    changed: List[str] = []

    def edit(
        rel: str, change: Callable[[str], str], bumps: Optional[Callable[[str], str]] = None
    ) -> None:
        path = root / rel
        old = path.read_text(encoding="utf-8")
        new = change(old)
        # counters such as Runtipi's tipi_version go up once per new version, not per run
        if bumps is not None and new != old:
            new = bumps(new)
        if new != old:
            path.write_text(new, encoding="utf-8")
            changed.append(rel)

    tag = f"{IMAGE}:{version}"
    pinned = f"{tag}@{digest}"

    rel = "deploy/casaos/AIMarketplaceMonitor/docker-compose.yml"
    edit(
        rel,
        lambda t: _sub(
            r'^(  version: ")[^"]+(")', rf"\g<1>{version}\g<2>", _sub(_PIN, tag, t, rel), rel
        ),
    )

    rel = "deploy/runtipi/ai-marketplace-monitor/docker-compose.json"
    edit(rel, lambda t: _sub(_PIN, tag, t, rel))
    rel = "deploy/runtipi/ai-marketplace-monitor/config.json"

    def runtipi_counters(t: str) -> str:
        t = _sub(
            r'("tipi_version": )(\d+)', lambda m: f"{m.group(1)}{int(m.group(2)) + 1}", t, rel
        )
        return _sub(r'("updated_at": )\d+', rf"\g<1>{int(time.time() * 1000)}", t, rel)

    edit(
        rel,
        lambda t: _sub(r'("version": ")[^"]+(")', rf"\g<1>{version}\g<2>", t, rel),
        runtipi_counters,
    )
    json.loads((root / rel).read_text(encoding="utf-8"))  # still valid JSON

    rel = "deploy/umbrel/ai-marketplace-monitor/docker-compose.yml"
    edit(rel, lambda t: _sub(_PIN, pinned, t, rel))
    rel = "deploy/umbrel/ai-marketplace-monitor/umbrel-app.yml"

    def umbrel_app(t: str) -> str:
        t = _sub(r'^(version: ")[^"]+(")', rf"\g<1>{version}\g<2>", t, rel)
        notes = f"releaseNotes: >-\n  Release notes: {RELEASES}/v{version}\n"
        if f"{RELEASES}/v{version}" in t:
            return t  # already this release's notes, maybe edited by hand: keep them
        return _sub(r"^releaseNotes:.*?\n(?=\n|\S)", notes, t, rel)

    edit(rel, umbrel_app)

    rel = "deploy/truenas/ai-marketplace-monitor/ix_values.yaml"
    edit(
        rel,
        lambda t: _sub(
            r"(repository: " + re.escape(IMAGE) + r'\n\s+tag: ")[^"]+(")',
            rf"\g<1>{version}@{digest}\g<2>",
            t,
            rel,
        ),
    )
    rel = "deploy/truenas/ai-marketplace-monitor/app.yaml"
    edit(
        rel,
        lambda t: _sub(r"^(app_version: )\S+", rf"\g<1>{version}", t, rel),
        # the app's own version: a new patch for each new aimm release
        lambda t: _sub(
            r"^(version: \d+\.\d+\.)(\d+)", lambda m: f"{m.group(1)}{int(m.group(2)) + 1}", t, rel
        ),
    )
    return changed


def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    changed = bump(args[0].removeprefix("v"), args[1])
    print("\n".join(f"updated {f}" for f in changed) or "the templates already pin this release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
