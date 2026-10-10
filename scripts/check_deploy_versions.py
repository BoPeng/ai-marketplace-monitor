#!/usr/bin/env python3
"""Check that the app-store templates in deploy/ pin the right aimm version.

The templates are bumped after each release, once the image (and so its digest) exists, as
CLAUDE.md describes. They must therefore pin:

- the version in pyproject.toml, once it is released (the tag ``v<version>`` exists), or
- the latest released version, while pyproject.toml names a version not yet released (the
  release pull request).

Within each template, every version field must agree with the image tag, and a pinned digest
must be the index digest of that tag in the registry (skipped with ``--offline``).

Usage: python scripts/check_deploy_versions.py [--offline]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "ghcr.io/bopeng/ai-marketplace-monitor"
REPOSITORY = "bopeng/ai-marketplace-monitor"
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class Pin:
    """A version (and maybe a digest) that one field of a template names."""

    file: str
    field: str
    version: str
    digest: Optional[str] = None
    needs_digest: bool = False  # the store requires the image pinned by digest


def _find(text: str, pattern: str, file: str) -> re.Match:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise ValueError(f"{file}: cannot find {pattern!r}")
    return match


def _image_pins(text: str, file: str, field: str, needs_digest: bool = False) -> List[Pin]:
    """Every reference to the image, as `IMAGE:version` or `IMAGE:version@sha256:...`."""
    pins = [
        Pin(file, field, m.group(1), m.group(2), needs_digest)
        for m in re.finditer(
            re.escape(IMAGE) + r":(\d+\.\d+\.\d+)(?:@(sha256:[0-9a-f]{64}))?", text
        )
    ]
    if not pins:
        raise ValueError(f"{file}: no pinned {IMAGE} image")
    return pins


def collect_pins(root: Path = ROOT) -> List[Pin]:
    """The versions pinned by the templates that do not use `latest`."""
    pins: List[Pin] = []

    def read(rel: str) -> str:
        return (root / rel).read_text(encoding="utf-8")

    rel = "deploy/casaos/AIMarketplaceMonitor/docker-compose.yml"
    text = read(rel)
    pins += _image_pins(text, rel, "image")
    pins.append(Pin(rel, "x-casaos version", _find(text, r'^  version: "([^"]+)"', rel).group(1)))

    rel = "deploy/runtipi/ai-marketplace-monitor/docker-compose.json"
    pins += _image_pins(read(rel), rel, "image")
    rel = "deploy/runtipi/ai-marketplace-monitor/config.json"
    pins.append(Pin(rel, "version", json.loads(read(rel))["version"]))

    rel = "deploy/umbrel/ai-marketplace-monitor/docker-compose.yml"
    pins += _image_pins(read(rel), rel, "image", needs_digest=True)
    rel = "deploy/umbrel/ai-marketplace-monitor/umbrel-app.yml"
    pins.append(Pin(rel, "version", _find(read(rel), r'^version: "([^"]+)"', rel).group(1)))

    rel = "deploy/truenas/ai-marketplace-monitor/ix_values.yaml"
    text = read(rel)
    m = _find(
        text,
        r"repository: " + re.escape(IMAGE) + r'\n\s+tag: "([^"@]+)(?:@(sha256:[0-9a-f]{64}))?"',
        rel,
    )
    pins.append(Pin(rel, "image tag", m.group(1), m.group(2), needs_digest=True))
    rel = "deploy/truenas/ai-marketplace-monitor/app.yaml"
    pins.append(Pin(rel, "app_version", _find(read(rel), r"^app_version: (\S+)", rel).group(1)))
    return pins


def project_version(root: Path = ROOT) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    return _find(text, r'^version = "([^"]+)"', "pyproject.toml").group(1)


def released_versions(root: Path = ROOT) -> List[str]:
    """The versions of the `vX.Y.Z` tags, oldest first."""
    tags = subprocess.run(
        ["git", "tag", "--list", "v*"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    versions = [t[1:] for t in tags if _VERSION.match(t[1:])]
    return sorted(versions, key=lambda v: tuple(int(p) for p in v.split(".")))


def expected_version(project: str, released: List[str]) -> str:
    """What the templates must pin: the project's version once released, else the latest release."""
    if project in released:
        return project
    if not released:
        raise ValueError("no release tags (vX.Y.Z) found; fetch the tags")
    return released[-1]


def registry_digest(version: str) -> str:
    """The index digest of the image's `version` tag in ghcr.io (anonymous pull)."""
    with urllib.request.urlopen(
        f"https://ghcr.io/token?scope=repository:{REPOSITORY}:pull", timeout=30
    ) as response:
        token = json.load(response)["token"]
    request = urllib.request.Request(
        f"https://ghcr.io/v2/{REPOSITORY}/manifests/{version}",
        method="HEAD",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.index.v1+json, "
            "application/vnd.docker.distribution.manifest.list.v2+json",
        },
    )
    # a fixed https URL; the version matched \d+.\d+.\d+
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return str(response.headers["Docker-Content-Digest"])


def check(
    pins: List[Pin],
    expected: str,
    digest_of: Optional[Callable[[str], str]] = None,
) -> List[str]:
    """Problems found; empty when every pin is right."""
    problems = [
        f"{p.file}: {p.field} is {p.version}, expected {expected}"
        for p in pins
        if p.version != expected
    ]
    problems += [
        f"{p.file}: {p.field} must pin the image by digest ({IMAGE}:{p.version}@sha256:...)"
        for p in pins
        if p.needs_digest and p.digest is None
    ]
    if digest_of is not None:
        digests: Dict[str, str] = {}
        for p in pins:
            if p.digest is None or p.version != expected:
                continue
            if p.version not in digests:
                digests[p.version] = digest_of(p.version)
            if p.digest != digests[p.version]:
                problems.append(
                    f"{p.file}: {p.field} pins {p.digest}, but {IMAGE}:{p.version} is "
                    f"{digests[p.version]}"
                )
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--offline", action="store_true", help="do not check digests in the registry"
    )
    args = parser.parse_args(argv)

    project = project_version()
    released = released_versions()
    expected = expected_version(project, released)
    pins = collect_pins()
    problems = check(pins, expected, None if args.offline else registry_digest)
    state: Tuple[str, str] = (
        ("released", "")
        if project in released
        else ("not released yet", f"; latest release {expected}")
    )
    print(f"pyproject.toml: {project} ({state[0]}{state[1]}); templates must pin {expected}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        print(
            "\nBump the templates as CLAUDE.md describes (Update the app-store templates).",
            file=sys.stderr,
        )
        return 1
    print(
        f"{len(pins)} pins in deploy/ name {expected}"
        + ("" if args.offline else ", with matching digests")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
