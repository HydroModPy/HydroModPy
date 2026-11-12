"""What ``hmp replay`` reads before it plays: the sealed directory and the project it writes into.

The replay itself runs in ``tests/integration``. Here the directories are made by
hand, so each case is exactly the seal it names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.project.replay import replay, replay_target
from hydromodpy.results.storage.contract import (
    PUBLICATION_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
)


def _sealed_run(root: Path, name: str = "probe.v2") -> Path:
    """Return ``root/runs/<name>``, holding the seal a replay reads."""
    run_dir = root / "runs" / name
    run_dir.mkdir(parents=True)
    (run_dir / RUN_CONFIG_FILENAME).write_text("", encoding="utf-8")
    (run_dir / RUN_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    (run_dir / RUN_INPUTS_FILENAME).write_text("{}", encoding="utf-8")
    return run_dir


def _copy(root: Path, name: str = "copy") -> Path:
    """Return ``root/<name>``, a published copy: both markers, no run directory."""
    folder = root / name
    folder.mkdir(parents=True)
    (folder / RUN_CONFIG_FILENAME).write_text("", encoding="utf-8")
    (folder / PUBLICATION_FILENAME).write_text("{}", encoding="utf-8")
    (folder / RUN_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    (folder / RUN_INPUTS_FILENAME).write_text("{}", encoding="utf-8")
    return folder


def test_a_run_directory_replays_into_the_project_above_it(tmp_path: Path) -> None:
    run_dir = _sealed_run(tmp_path)
    target = replay_target(run_dir)
    assert target.source == run_dir.resolve()
    assert target.project_root == tmp_path.resolve()


def test_the_config_toml_of_a_run_names_the_same_directory(tmp_path: Path) -> None:
    run_dir = _sealed_run(tmp_path)
    target = replay_target(run_dir / RUN_CONFIG_FILENAME)
    assert target.source == run_dir.resolve()


def test_a_bare_name_is_read_under_the_runs_of_the_project(tmp_path: Path) -> None:
    """A name alone is read under ``runs/`` of the project ``-w`` names."""
    run_dir = _sealed_run(tmp_path)
    target = replay_target("probe.v2", base=tmp_path)
    assert target.source == run_dir.resolve()


def test_a_name_that_names_nothing_is_refused_with_the_path_it_looked_for(
    tmp_path: Path,
) -> None:
    (tmp_path / "runs").mkdir()
    with pytest.raises(ConfigError, match=r"runs/absent does not exist"):
        replay_target("absent", base=tmp_path)


def test_a_published_copy_with_no_project_named_is_refused(tmp_path: Path) -> None:
    folder = _copy(tmp_path / "elsewhere")
    with pytest.raises(ConfigError, match="-w"):
        replay_target(folder)


def test_a_directory_with_no_seal_is_refused_naming_the_verb(tmp_path: Path) -> None:
    (tmp_path / "runs" / "probe").mkdir(parents=True)
    (tmp_path / "runs" / "probe" / RUN_CONFIG_FILENAME).write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="hmp replay"):
        replay_target(tmp_path / "runs" / "probe")


def test_a_run_without_inputs_json_cannot_be_pinned_and_is_refused(tmp_path: Path) -> None:
    run_dir = _sealed_run(tmp_path)
    (run_dir / RUN_INPUTS_FILENAME).unlink()
    with pytest.raises(ConfigError, match=RUN_INPUTS_FILENAME):
        replay_target(run_dir)


def test_a_copy_missing_its_manifest_is_refused(tmp_path: Path) -> None:
    folder = _copy(tmp_path / "elsewhere")
    (folder / RUN_MANIFEST_FILENAME).unlink()
    with pytest.raises(ConfigError, match=RUN_MANIFEST_FILENAME):
        replay_target(folder)


def test_a_run_outside_runs_directory_needs_its_project_named(tmp_path: Path) -> None:
    run_dir = _sealed_run(tmp_path)
    moved = tmp_path / "kept" / "probe.v2"
    moved.parent.mkdir()
    run_dir.rename(moved)
    with pytest.raises(ConfigError, match="-w"):
        replay_target(moved)
    assert replay_target(moved, base=tmp_path).project_root == tmp_path.resolve()


def test_replay_of_a_directory_with_no_seal_stops_before_reading_it(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="carries no seal"):
        replay(tmp_path)
