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
from ai_marketplace_monitor.configure.writer import CommitOutcome, commit_sections

MAIN = """
# my AI
[ai.unitysvc]
api_key = "svcpass_testkey"

[user.me]
pushbullet_token = "${PUSHBULLET_TOKEN}"  # keep me

[marketplace.facebook]
# where I live
search_city = "houston"
radius = 30
"""


def setup(tmp_path: Path, *texts: str) -> Tuple[List[Path], Dict[str, Any]]:
    files = []
    for index, text in enumerate(texts):
        path = tmp_path / f"config{index}.toml"
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        files.append(path)
    _, user = load_config_dicts(files)
    return files, user


async def test_only_the_changed_section_is_edited_in_place(tmp_path: Path) -> None:
    files, user = setup(tmp_path, MAIN)
    new = copy.deepcopy(user)
    new["marketplace"]["facebook"] = {
        "request": "Houston, 50 miles",
        "search_city": "houston",
        "radius": 50,
    }
    ui = ScriptedSetupUI(["yes"])

    assert (
        await commit_sections(ui, new, user, files, tmp_path / "backups") is CommitOutcome.WRITTEN
    )
    text = files[0].read_text()
    for kept in (
        "# my AI",
        "# where I live",
        'pushbullet_token = "${PUSHBULLET_TOKEN}"  # keep me',
    ):
        assert kept in text
    assert "[notification" not in text
    assert tomllib.loads(text)["marketplace"]["facebook"] == {
        "search_city": "houston",
        "radius": 50,
        "request": "Houston, 50 miles",
    }
    (backup,) = (tmp_path / "backups").iterdir()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    diff = next(m for m in ui.said() if m.startswith("```diff"))
    assert "-radius = 30" in diff and "+radius = 50" in diff and "user.me" not in diff


async def test_new_section_and_removed_keys(tmp_path: Path) -> None:
    files, user = setup(tmp_path, MAIN)
    new = copy.deepcopy(user)
    new["marketplace"]["facebook"] = {"search_city": "houston"}
    new["marketplace"]["other"] = {"search_city": "dallas"}
    assert await commit_sections(ScriptedSetupUI(["yes"]), new, user, files, tmp_path / "b") is (
        CommitOutcome.WRITTEN
    )
    data = tomllib.loads(files[0].read_text())
    assert data["marketplace"] == {
        "facebook": {"search_city": "houston"},
        "other": {"search_city": "dallas"},
    }


async def test_several_files_edit_the_file_that_defines_the_section(tmp_path: Path) -> None:
    files, user = setup(
        tmp_path,
        '[ai.unitysvc]\napi_key = "k"\n',
        '# items\n[marketplace.facebook]\nsearch_city = "dallas"\n',
    )
    new = copy.deepcopy(user)
    new["marketplace"]["facebook"]["search_city"] = "austin"
    assert await commit_sections(ScriptedSetupUI(["yes"]), new, user, files, tmp_path / "b") is (
        CommitOutcome.WRITTEN
    )
    assert files[0].read_text() == '[ai.unitysvc]\napi_key = "k"\n'
    assert "# items" in files[1].read_text() and 'search_city = "austin"' in files[1].read_text()


async def test_declined_and_unchanged(tmp_path: Path) -> None:
    files, user = setup(tmp_path, MAIN)
    before = files[0].read_text()
    new = copy.deepcopy(user)
    new["marketplace"]["facebook"]["radius"] = 10
    assert await commit_sections(ScriptedSetupUI(["no"]), new, user, files, tmp_path / "b") is (
        CommitOutcome.DECLINED
    )
    ui = ScriptedSetupUI([])
    assert await commit_sections(ui, user, user, files, tmp_path / "b") is CommitOutcome.WRITTEN
    assert ui.said("success") == ["Nothing changed; your config is left as it is."]
    assert files[0].read_text() == before


async def test_override_in_a_later_file_is_reported(tmp_path: Path) -> None:
    files, user = setup(
        tmp_path,
        '[marketplace.facebook]\nsearch_city = "houston"\nradius = 30\n',
        '[marketplace.facebook]\nsearch_city = "dallas"\n',
    )
    new = copy.deepcopy(user)
    new["marketplace"]["facebook"]["radius"] = 50
    del new["marketplace"]["facebook"]["search_city"]
    ui = ScriptedSetupUI(["yes"])
    assert await commit_sections(ui, new, user, files, tmp_path / "b") is CommitOutcome.FAILED
    assert "does not read back as written" in ui.said("error")[0]


async def test_file_changed_during_confirmation_is_not_overwritten(tmp_path: Path) -> None:
    files, user = setup(tmp_path, MAIN)
    new = copy.deepcopy(user)
    new["marketplace"]["facebook"]["radius"] = 50

    class EditingUI(ScriptedSetupUI):
        async def confirm(self, prompt: str, default: bool = True) -> bool:
            files[0].write_text(files[0].read_text() + "\n# edited meanwhile\n")
            return True

    ui = EditingUI([])
    assert await commit_sections(ui, new, user, files, tmp_path / "b") is CommitOutcome.FAILED
    assert "changed while you were reviewing" in ui.said("error")[0]
    text = files[0].read_text()
    assert "# edited meanwhile" in text and "radius = 30" in text
    assert not (tmp_path / "b").exists()  # nothing backed up or written
