"""The verb ``open`` hands back what a path stands for: a project, a run, a session or a workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.project import api
from hydromodpy.project.accessors import Workspace
from hydromodpy.project.facade import Project
from hydromodpy.results.errors import RunNotSealedError
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt

pytestmark = pytest.mark.fast


def test_a_project_file_and_a_folder_inside_open_the_same_project(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    (project / "configs").mkdir()

    for where in (str(project), project / "project.toml", project / "configs"):
        proj = api.open(where)
        assert isinstance(proj, Project)
        assert proj.root == project.resolve()


def test_a_run_that_never_completed_is_refused_with_its_outcome(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_attempt(project, "runs/broken", status="failed", error=("SolverError", "diverged"))

    with pytest.raises(RunNotSealedError, match="outcome.json"):
        api.open(project / "runs" / "broken")


def test_a_workspace_root_opens_as_a_workspace(tmp_path: Path) -> None:
    make_project(tmp_path / "projects" / "demo")

    workspace = api.open(tmp_path)

    assert isinstance(workspace, Workspace)
    assert workspace.projects == ["demo"]
    assert isinstance(workspace["demo"], Project)


def test_a_path_that_stands_for_nothing_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        api.open(tmp_path / "missing")
    (tmp_path / "loose").mkdir()
    with pytest.raises(FileNotFoundError, match="no project"):
        api.open(tmp_path / "loose")


def test_a_folder_of_projects_names_them(tmp_path: Path) -> None:
    """A folder that is no project but holds some names them in the refusal."""
    folder = (tmp_path / "studies").resolve()
    make_project(folder / "demo")
    make_project(folder / "group" / "other")
    with pytest.raises(FileNotFoundError, match="This folder holds projects") as caught:
        api.open(folder)
    message = str(caught.value)
    assert str(folder / "demo") in message
    assert str(folder / "group" / "other") in message


def test_a_workspace_reads_the_runs_of_every_project_by_site(tmp_path: Path) -> None:
    """``open(<workspace root>).runs(site=)`` reads the sealed rows of each project, no index needed."""
    first = make_project(tmp_path / "projects" / "a")
    second = make_project(tmp_path / "projects" / "b")
    seal_run(first, "one", site="nancon")
    seal_run(second, "two", site="nancon")
    seal_run(second, "three", site="couesnon")

    runs = api.open(tmp_path).runs(site="nancon")

    assert sorted(runs["name"]) == ["one", "two"]
    assert not catalog_path_for(first).exists()
    assert not catalog_path_for(second).exists()
