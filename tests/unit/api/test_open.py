"""Unit tests for ``hmp.open`` (single catalog door + fail-fast)."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.core.state.paths import catalog_path_for

pytestmark = pytest.mark.fast


def test_open_missing_catalog_raises(tmp_path: Path) -> None:
    """``hmp.open`` on an empty directory fails fast, no phantom catalog."""
    with pytest.raises(FileNotFoundError):
        hmp.open(tmp_path)
    assert not catalog_path_for(tmp_path).exists()


def test_open_create_returns_simulation_catalog(tmp_path: Path) -> None:
    """``create=True`` opens (and initialises) a Catalog."""
    cat = hmp.open(tmp_path, create=True)
    try:
        assert isinstance(cat, hmp.Catalog)
    finally:
        cat.close()


def test_open_accepts_string_workspace(tmp_path: Path) -> None:
    """``hmp.open`` accepts a string path."""
    cat = hmp.open(str(tmp_path), create=True)
    try:
        assert isinstance(cat, hmp.Catalog)
    finally:
        cat.close()


def test_open_existing_catalog_without_create(tmp_path: Path) -> None:
    """Once a catalog exists, ``hmp.open`` works with the default create=False."""
    hmp.open(tmp_path, create=True).close()
    cat = hmp.open(tmp_path)
    try:
        assert isinstance(cat, hmp.Catalog)
        assert cat.frame.empty
    finally:
        cat.close()


def test_open_on_a_workspace_root_names_its_projects(tmp_path: Path) -> None:
    """A workspace root holds no index; the error names the projects that do."""
    project = tmp_path / "projects" / "nancon"
    project.mkdir(parents=True)
    (project / "project.toml").write_text("", encoding="utf-8")
    hmp.open(project, create=True).close()

    with pytest.raises(FileNotFoundError, match="projects with a catalog") as info:
        hmp.open(tmp_path)
    assert str(project.resolve()) in str(info.value)
