"""Opt-in container tests: set AIMM_DOCKER_TEST_IMAGE to a built Docker image."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("uid,gid", [(1000, 1000), (1234, 1234)])
def test_entrypoint_migrates_files_inside_an_already_owned_directory(
    legacy: bool, uid: int, gid: int
) -> None:
    image = os.environ.get("AIMM_DOCKER_TEST_IMAGE")
    if not image:
        pytest.skip("set AIMM_DOCKER_TEST_IMAGE to run Docker entrypoint tests")
    entrypoint = Path(__file__).resolve().parents[1] / "docker" / "entrypoint.sh"
    data = "/root/.ai-marketplace-monitor" if legacy else "/data"
    # All data is disposable and stays in the container. Both a root-only config
    # and a root-owned cache must migrate, even though their parent has the right UID.
    script = f"""
set -eu
mkdir -p {data}/cache
chown {uid}:{gid} {data}
printf config > {data}/config.toml
printf cache > {data}/cache/cache.db
chmod 600 {data}/config.toml {data}/cache/cache.db
ln -s /etc/passwd {data}/outside
/test-entrypoint /bin/sh -c '
    test "$(id -u)" = "{uid}"
    test -r /data/config.toml && test -w /data/config.toml
    test -r /data/cache/cache.db && test -w /data/cache/cache.db
    test "$(stat -c %u /etc/passwd)" = 0
    printf success
'
"""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-e",
            f"PUID={uid}",
            "-e",
            f"PGID={gid}",
            "-v",
            f"{entrypoint}:/test-entrypoint:ro",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "success" in result.stdout
