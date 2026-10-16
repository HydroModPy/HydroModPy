"""Unit tests for ``hmp.report``: the session directory alone, never the index."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.core.exceptions import ConfigMissingError
from tests._helpers.sealed_runs import make_project, write_session_dir

pytestmark = pytest.mark.fast


def _capture_render(monkeypatch) -> dict:
    captured: dict = {}

    def fake_render(*, session_dir: Path) -> Path:
        captured["session_dir"] = session_dir
        return session_dir / "report" / "index.html"

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.calibration.step_render_calibration_report", fake_render
    )
    return captured


def test_report_names_the_session_by_its_directory(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "calibration")
    write_session_dir(project, "calibration.v2")
    captured = _capture_render(monkeypatch)

    result = hmp.report("calibration", workspace=project)

    assert captured["session_dir"] == project.resolve() / "sessions" / "calibration"
    assert result == captured["session_dir"] / "report" / "index.html"


def test_report_default_is_the_latest_session_of_the_cwd_project(
    monkeypatch, tmp_path: Path
) -> None:
    from datetime import timedelta

    from tests._helpers.sealed_runs import NOW

    project = make_project(tmp_path / "p")
    write_session_dir(project, "old", started_at=NOW - timedelta(days=2))
    write_session_dir(project, "new", started_at=NOW)
    (project / "configs").mkdir()
    monkeypatch.chdir(project / "configs")
    captured = _capture_render(monkeypatch)

    hmp.report()

    assert captured["session_dir"].name == "new"


def test_report_refuses_an_unknown_session_with_the_list(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "calibration")
    _capture_render(monkeypatch)

    with pytest.raises(ConfigMissingError, match="calibration"):
        hmp.report("nope", workspace=project)


def test_report_never_opens_the_index(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "calibration")
    _capture_render(monkeypatch)

    def refuse(*_args, **_kwargs):
        raise AssertionError("hmp.report opened the index")

    monkeypatch.setattr("hydromodpy.results.catalog.facade.Catalog.__init__", refuse)
    hmp.report("calibration", workspace=project)
