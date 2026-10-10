"""scripts/check_deploy_versions.py: the app-store templates pin the right aimm version."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_deploy_versions", ROOT / "scripts" / "check_deploy_versions.py"
)
assert _spec is not None and _spec.loader is not None
cdv: Any = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cdv  # dataclasses look their module up there
_spec.loader.exec_module(cdv)


def test_templates_follow_the_released_version() -> None:
    # pyproject.toml is released: the templates pin it
    assert cdv.expected_version("0.10.11", ["0.10.9", "0.10.10", "0.10.11"]) == "0.10.11"
    # the release pull request bumps pyproject.toml first: the templates keep the last release
    assert cdv.expected_version("0.10.12", ["0.10.10", "0.10.11"]) == "0.10.11"
    with pytest.raises(ValueError, match="fetch the tags"):
        cdv.expected_version("0.10.12", [])


def test_the_templates_in_the_repository_agree() -> None:
    pins = cdv.collect_pins(ROOT)
    files = {p.file for p in pins}
    assert len(files) == 7  # casaos, runtipi x2, umbrel x2, truenas x2
    assert len({p.version for p in pins}) == 1
    assert {p.file for p in pins if p.digest} == {
        "deploy/umbrel/ai-marketplace-monitor/docker-compose.yml",
        "deploy/truenas/ai-marketplace-monitor/ix_values.yaml",
    }


@pytest.fixture
def deploy_copy(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "deploy", tmp_path / "deploy")
    return tmp_path


def test_a_stale_pin_is_reported(deploy_copy: Path) -> None:
    pins = cdv.collect_pins(deploy_copy)
    version = pins[0].version
    app = deploy_copy / "deploy/truenas/ai-marketplace-monitor/app.yaml"
    app.write_text(app.read_text().replace(f"app_version: {version}", "app_version: 0.0.1"))
    problems = cdv.check(cdv.collect_pins(deploy_copy), version)
    assert problems == [
        f"deploy/truenas/ai-marketplace-monitor/app.yaml: app_version is 0.0.1, expected {version}"
    ]


def test_a_digest_must_match_the_registry(deploy_copy: Path) -> None:
    pins = cdv.collect_pins(deploy_copy)
    version = pins[0].version
    pinned = next(p.digest for p in pins if p.digest)
    asked: list = []

    def registry(v: str) -> str:
        asked.append(v)
        return pinned

    assert cdv.check(pins, version, registry) == []
    assert asked == [version]  # asked once for all the pins of a version
    other = "sha256:" + "0" * 64
    problems = cdv.check(pins, version, lambda v: other)
    assert len(problems) == 2 and all(f"is {other}" in p for p in problems)


def test_umbrel_and_truenas_must_pin_a_digest(deploy_copy: Path) -> None:
    """A tag without its digest would pass the version check; these stores require one."""
    values = deploy_copy / "deploy/truenas/ai-marketplace-monitor/ix_values.yaml"
    pins = cdv.collect_pins(deploy_copy)
    version = pins[0].version
    digest = next(p.digest for p in pins if p.digest)
    values.write_text(values.read_text().replace(f"{version}@{digest}", version))
    problems = cdv.check(cdv.collect_pins(deploy_copy), version)
    assert problems == [
        "deploy/truenas/ai-marketplace-monitor/ix_values.yaml: image tag must pin the image by"
        f" digest (ghcr.io/bopeng/ai-marketplace-monitor:{version}@sha256:...)"
    ]


def test_a_missing_field_is_an_error(deploy_copy: Path) -> None:
    compose = deploy_copy / "deploy/runtipi/ai-marketplace-monitor/docker-compose.json"
    compose.write_text(compose.read_text().replace("ghcr.io/bopeng", "docker.io/someone"))
    with pytest.raises(ValueError, match="no pinned"):
        cdv.collect_pins(deploy_copy)
