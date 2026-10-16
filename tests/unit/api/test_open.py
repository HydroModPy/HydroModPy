"""Unit tests for ``hmp.open``: the reader of a project index, and its fail-fast."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run

pytestmark = pytest.mark.fast


def test_open_missing_index_raises(tmp_path: Path) -> None:
    """``hmp.open`` on a project without an index fails fast and writes nothing."""
    project = make_project(tmp_path / "p")
    with pytest.raises(FileNotFoundError, match="hmp catalog reindex"):
        hmp.open(project)
    assert not catalog_path_for(project).exists()


def test_open_reads_the_index_rebuilt_from_the_runs(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    sim_id = seal_run(project, "baseline")
    rebuild_index(project)

    cat = hmp.open(project)
    try:
        assert isinstance(cat, hmp.Catalog)
        assert cat.frame["sim_id"].astype(str).tolist() == [sim_id]
    finally:
        cat.close()


def test_open_accepts_a_string_and_a_folder_inside_the_project(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    rebuild_index(project)
    (project / "configs").mkdir()

    for where in (str(project), project / "configs"):
        cat = hmp.open(where)
        try:
            assert cat.project_path == project.resolve()
            assert cat.frame.empty
        finally:
            cat.close()


def test_open_on_a_workspace_root_names_its_projects(tmp_path: Path) -> None:
    """A workspace root holds no index; the error names the projects that do."""
    project = make_project(tmp_path / "projects" / "demo")
    rebuild_index(project)

    with pytest.raises(FileNotFoundError, match="projects with a catalog") as info:
        hmp.open(tmp_path)
    assert str(project.resolve()) in str(info.value)
