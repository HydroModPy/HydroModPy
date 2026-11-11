"""``show(ref, what="report")`` of a session: the session directory alone, never the index."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.project import api
from hydromodpy.results.catalog.discovery import SimulationNotFoundError
from tests._helpers.sealed_runs import make_project, write_session_dir

pytestmark = pytest.mark.fast


def _capture_render(monkeypatch) -> dict:
    captured: dict = {}

    def fake_render(session_dir: Path, **_options) -> Path:
        captured["session_dir"] = session_dir
        return session_dir / "report" / "index.html"

    monkeypatch.setattr("hydromodpy.project.report.report_session", fake_render)
    return captured


def test_report_names_the_session_by_its_directory(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "calibration")
    write_session_dir(project, "calibration.v2")
    captured = _capture_render(monkeypatch)

    result = api.show("calibration", what="report", workspace=project)

    assert captured["session_dir"] == project.resolve() / "sessions" / "calibration"
    assert result == captured["session_dir"] / "report" / "index.html"


def test_a_name_without_workspace_is_not_read_in_the_project_of_the_cwd(
    monkeypatch, tmp_path: Path
) -> None:
    """The library never looks for a project above the working directory."""
    project = make_project(tmp_path / "p")
    write_session_dir(project, "new")
    (project / "configs").mkdir()
    monkeypatch.chdir(project / "configs")
    captured = _capture_render(monkeypatch)

    with pytest.raises(NothingThereError, match="workspace="):
        api.show("new", what="report")

    assert captured == {}
    assert api.show(project / "sessions" / "new", what="report").parent.name == "report"


def test_report_refuses_an_unknown_session_with_the_list(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "calibration")
    _capture_render(monkeypatch)

    with pytest.raises(SimulationNotFoundError, match="calibration"):
        api.show("nope", what="report", workspace=project)


def test_report_never_opens_the_index(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "calibration")
    _capture_render(monkeypatch)

    def refuse(*_args, **_kwargs):
        raise AssertionError("the report opened the index")

    monkeypatch.setattr("hydromodpy.results.catalog.facade.Catalog.__init__", refuse)
    api.show("calibration", what="report", workspace=project)
