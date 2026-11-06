"""Validate bundled example projects against the root config schema.

A project with ``[sites]`` is not one configuration but a plan of cases. It
is checked the way ``hmp config check`` checks it, case by case, and its
recipe files are checked with it rather than loaded alone.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.project.check import check_project

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_PROJECTS = Path("examples/projects")

requires_git = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists(),
    reason="example configs are discovered through git ls-files",
)


def _tracked_toml_files() -> list[Path]:
    """Return the TOML files git tracks under ``examples/projects``.

    Untracked scratch configs left in a user project directory are ignored on
    purpose: they are not part of the shipped examples.
    """
    if not (REPO_ROOT / ".git").exists():
        return []
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", EXAMPLES_PROJECTS.as_posix()],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(
        REPO_ROOT / entry for entry in completed.stdout.split("\0") if entry.endswith(".toml")
    )


def _declares_calibration(toml_file: Path) -> bool:
    """Tell whether the merged payload of *toml_file* carries a calibration section."""
    return "calibration" in load_toml_with_base_config(toml_file)


def _belongs_to_sites_project(toml_file: Path) -> bool:
    """Tell whether *toml_file* or its ``base_config`` chain declares ``[sites]``."""
    return "sites" in load_toml_with_base_config(toml_file)


def _is_an_overlay(toml_file: Path) -> bool:
    """Tell whether *toml_file* needs a project under it, for want of a ``[geographic]``."""
    return "geographic" not in load_toml_with_base_config(toml_file)


def _identifier(toml_file: Path) -> str:
    return toml_file.relative_to(REPO_ROOT).as_posix()


_TRACKED_TOML_FILES = _tracked_toml_files()
_PROJECT_CONFIGS = [item for item in _TRACKED_TOML_FILES if item.name == "project.toml"]
_CALIBRATION_CONFIGS = [
    item
    for item in _TRACKED_TOML_FILES
    if _declares_calibration(item)
    and not _belongs_to_sites_project(item)
    and not _is_an_overlay(item)
]


@requires_git
def test_examples_projects_are_discovered() -> None:
    assert _PROJECT_CONFIGS
    assert _CALIBRATION_CONFIGS


@requires_git
@pytest.mark.parametrize("project_file", _PROJECT_CONFIGS, ids=_identifier)
def test_examples_projects_load(project_file: Path) -> None:
    if _belongs_to_sites_project(project_file):
        report = check_project(project_file)
        assert report.kind == "sites"
        assert report.ok, report.errors
        assert report.n_cases
        return
    HydroModPyConfig.from_toml(project_file)


@requires_git
@pytest.mark.parametrize("calibration_file", _CALIBRATION_CONFIGS, ids=_identifier)
def test_examples_calibration_configs_load(calibration_file: Path) -> None:
    cfg = HydroModPyConfig.from_toml(calibration_file)
    assert cfg.calibration is not None
