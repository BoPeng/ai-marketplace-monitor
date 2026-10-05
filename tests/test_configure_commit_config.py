import copy
import stat
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.config import load_config_dicts
from ai_marketplace_monitor.configure.ui import ScriptedSetupUI
from ai_marketplace_monitor.configure.writer import CommitOutcome, commit_config
from ai_marketplace_monitor.normalize import expand

MAIN = """
# my AI
[ai.unitysvc]
api_key = "svcpass_testkey"

[user.me]
pushbullet_token = "abc"
"""


def setup(
    tmp_path: Path, *texts: str
) -> Tuple[List[Path], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    files = []
    for index, text in enumerate(texts):
        path = tmp_path / f"config{index}.toml"
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        files.append(path)
    system, user = load_config_dicts(files)
    return files, system, user, expand(user, system, partial=True).config


def with_marketplace(expanded: Dict[str, Any]) -> Dict[str, Any]:
    new = copy.deepcopy(expanded)
    new["marketplace"] = {"facebook": {"request": "Houston", "search_city": ["houston"]}}
    return new


async def test_single_file_is_rewritten_normalized_with_backup(tmp_path: Path) -> None:
    files, system, user, expanded = setup(tmp_path, MAIN)
    ui = ScriptedSetupUI(["yes"])

    outcome = await commit_config(
        ui, with_marketplace(expanded), files, system, user, tmp_path / "backups"
    )
    assert outcome is CommitOutcome.WRITTEN
    text = files[0].read_text()
    assert "# my AI" not in text
    assert tomllib.loads(text)["marketplace"]["facebook"]["search_city"] == ["houston"]
    (backup,) = (tmp_path / "backups").iterdir()
    assert "# my AI" in backup.read_text()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert any("comments are dropped" in m for m in ui.said("warning"))
    assert any("+[marketplace.facebook]" in m for m in ui.said())


async def test_several_files_write_only_changed_sections(tmp_path: Path) -> None:
    second = '# items\n[marketplace.facebook]\nsearch_city = "dallas"\n'
    files, system, user, expanded = setup(tmp_path, MAIN, second)
    ui = ScriptedSetupUI(["yes"])

    outcome = await commit_config(
        ui, with_marketplace(expanded), files, system, user, tmp_path / "backups"
    )
    assert outcome is CommitOutcome.WRITTEN
    assert "# my AI" in files[0].read_text()  # untouched
    text = files[1].read_text()
    assert "# items" in text
    assert tomllib.loads(text)["marketplace"]["facebook"] == {
        "request": "Houston",
        "search_city": ["houston"],
    }


async def test_declined_write_changes_nothing(tmp_path: Path) -> None:
    files, system, user, expanded = setup(tmp_path, MAIN)
    before = files[0].read_text()
    outcome = await commit_config(
        ScriptedSetupUI(["no"]), with_marketplace(expanded), files, system, user, tmp_path / "b"
    )
    assert outcome is CommitOutcome.DECLINED
    assert files[0].read_text() == before


async def test_invalid_config_fails_before_writing(tmp_path: Path) -> None:
    files, system, user, expanded = setup(tmp_path, MAIN)
    bad = with_marketplace(expanded)
    bad["marketplace"]["facebook"]["condition"] = ["mint"]
    ui = ScriptedSetupUI([])
    outcome = await commit_config(ui, bad, files, system, user, tmp_path / "b")
    assert outcome is CommitOutcome.FAILED
    assert "not valid" in ui.said("error")[0]


async def test_unchanged_config_writes_nothing(tmp_path: Path) -> None:
    files, system, user, expanded = setup(tmp_path, '[ai.unitysvc]\napi_key = "svcpass_testkey"\n')
    ui = ScriptedSetupUI([])
    assert await commit_config(ui, expanded, files, system, user, tmp_path / "b") is (
        CommitOutcome.WRITTEN
    )
    assert ui.said("success") == ["Nothing to change in the config files."]
