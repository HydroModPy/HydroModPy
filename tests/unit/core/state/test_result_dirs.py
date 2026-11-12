"""Where the root of a project is found from a result folder, and how a result folder is spelled.

A run is ``runs/<name>`` and a kept trial is ``sessions/<name>/trials/<n>``, both
relative to the project root. The root is the folder that holds ``project.toml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.layout import (
    CATALOG_FILENAME,
    CONFIGS_DIRNAME,
    PROJECT_MARKER_FILENAME,
    RUNS_DIRNAME,
)
from hydromodpy.core.state.result_dirs import (
    parse_rel_dir,
    refuse_a_sealed_run_as_project,
    resolve_project_root,
    run_dir_rel,
    trial_dir_rel,
)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "cheze"
    (root / RUNS_DIRNAME).mkdir(parents=True)
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def test_root_walks_up_to_the_marker(tmp_path: Path) -> None:
    root = _project(tmp_path)
    assert resolve_project_root(root) == root
    assert resolve_project_root(root / RUNS_DIRNAME) == root


def test_root_ignores_a_missing_catalog(tmp_path: Path) -> None:
    root = _project(tmp_path)
    catalog = root / CATALOG_FILENAME
    catalog.write_bytes(b"")
    assert resolve_project_root(root / RUNS_DIRNAME) == root
    catalog.unlink()
    assert resolve_project_root(root / RUNS_DIRNAME) == root


def test_catalog_alone_anchors_nothing(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    (root / RUNS_DIRNAME).mkdir(parents=True)
    (root / CATALOG_FILENAME).write_bytes(b"")
    assert resolve_project_root(root / RUNS_DIRNAME) == root / RUNS_DIRNAME


def test_root_defaults_to_the_start(tmp_path: Path) -> None:
    assert resolve_project_root(tmp_path) == tmp_path


@pytest.mark.parametrize(
    ("relative", "held", "answer"),
    [
        pytest.param("runs/first", "outcome.json", ".", id="a-run-of-a-flat-project"),
        pytest.param("runs/first.v2", "manifest.json", ".", id="a-sealed-run"),
        pytest.param("sessions/case", "outcome.json", ".", id="a-session"),
        pytest.param("sessions/case/trials/0003", "outcome.json", ".", id="a-kept-trial"),
        pytest.param("runs/first", "notes.txt", "runs/first", id="a-folder-of-the-user"),
        pytest.param("elsewhere/base", "manifest.json", "elsewhere/base", id="a-copy-of-a-run"),
    ],
)
def test_root_of_a_result_directory(tmp_path: Path, relative: str, held: str, answer: str) -> None:
    folder = tmp_path / relative
    folder.mkdir(parents=True)
    (folder / held).write_text("{}", encoding="utf-8")
    assert resolve_project_root(folder) == (tmp_path / answer).resolve()


def test_sealed_run_is_no_project(tmp_path: Path) -> None:
    refuse_a_sealed_run_as_project(tmp_path)
    for name in ("manifest.json", "config.toml"):
        (tmp_path / name).write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="-w <project>"):
        refuse_a_sealed_run_as_project(tmp_path)


def test_orphan_configs_dir_is_refused(tmp_path: Path) -> None:
    configs = tmp_path / "orphan" / CONFIGS_DIRNAME
    configs.mkdir(parents=True)
    with pytest.raises(ConfigError, match=PROJECT_MARKER_FILENAME):
        resolve_project_root(configs)


def test_configs_dir_under_a_marker(tmp_path: Path) -> None:
    root = _project(tmp_path)
    configs = root / CONFIGS_DIRNAME
    configs.mkdir()
    assert resolve_project_root(configs) == root


@pytest.mark.parametrize(
    "text",
    [
        "runs",
        "runs/",
        "runs/a/b",
        "/runs/a",
        "share/a",
        "sessions/a/trials",
        "sessions/a/trials/4",
        "sessions/a/trials/00004",
        "sessions/a/trials/-001",
        "sessions/a/phases/0001",
        "runs/..",
        "runs\\a",
    ],
)
def test_bad_rel_dir_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="not a result directory"):
        parse_rel_dir(text)


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b"])
def test_bad_run_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError):
        run_dir_rel(name)


def test_negative_trial_is_refused() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        trial_dir_rel("s", -1)
