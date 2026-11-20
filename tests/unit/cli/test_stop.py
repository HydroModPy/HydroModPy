"""``hmp stop REF`` and ``hmp.stop`` write the stop flag of a running run or session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import hydromodpy as hmp
import hydromodpy.results.storage.attempt as attempt_module
from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.core.state.layout import stop_flag_for
from hydromodpy.results.storage.attempt import claim_run_directory, finish_attempt
from tests._helpers.sealed_runs import make_project
from tests.unit.cli._hmp import run_hmp


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return make_project(tmp_path / "demo")


def _session(project: Path, name: str, status: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = project / "sessions" / name
    folder.mkdir(parents=True)
    (folder / "session.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        attempt_module, "read_session", lambda directory: argparse.Namespace(status=status)
    )
    return folder


def test_stop_a_session(project: Path, monkeypatch) -> None:
    session = _session(project, "calib", "running", monkeypatch)

    assert hmp.stop("sessions/calib", workspace=project) == stop_flag_for(session)
    assert hmp.stop("calib", workspace=project) == stop_flag_for(session)


@pytest.mark.parametrize(
    ("ref", "message"),
    [
        pytest.param("ghost", "'ghost' names no run and no calibration session", id="nothing"),
        pytest.param("runs/ghost", "'runs/ghost' names no run", id="no run"),
        pytest.param("sessions/ghost", "names no run and no calibration session", id="no session"),
        pytest.param("ended", "runs/ended is failed, there is nothing to stop", id="ended run"),
        pytest.param("calib", "sessions/calib is completed, there is nothing to stop", id="closed"),
    ],
)
def test_stop_refusals(project: Path, monkeypatch, ref: str, message: str) -> None:
    ended = claim_run_directory(project, "ended", case_id="ended", project="demo")
    finish_attempt(ended.run_dir, status="failed", error=RuntimeError("boom"))
    _session(project, "calib", "completed", monkeypatch)

    with pytest.raises(NothingThereError, match=message):
        hmp.stop(ref, workspace=project)
    assert not stop_flag_for(ended.run_dir).exists()


def test_command_writes_flag(project: Path, monkeypatch, capsys) -> None:
    claim = claim_run_directory(project, "case", case_id="case", project="demo")

    code = run_hmp(monkeypatch, "stop", "case", "-w", str(project), "--format", "json")

    assert code == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data == {"ref": "case", "flag": str(stop_flag_for(claim.run_dir))}
    assert stop_flag_for(claim.run_dir).is_file()


def test_command_on_ended_run(project: Path, monkeypatch, capsys) -> None:
    ended = claim_run_directory(project, "case", case_id="case", project="demo")
    finish_attempt(ended.run_dir, status="completed")

    code = run_hmp(monkeypatch, "stop", "case", "-w", str(project))

    assert code == 10
    assert "there is nothing to stop" in capsys.readouterr().err


def test_stop_takes_the_directory_of_a_run_by_its_path(project: Path, monkeypatch) -> None:
    claim = claim_run_directory(project, "case", case_id="case", project="demo")

    assert hmp.stop(claim.run_dir, workspace=project) == stop_flag_for(claim.run_dir)
    assert hmp.stop(str(claim.run_dir), workspace=project) == stop_flag_for(claim.run_dir)
    assert run_hmp(monkeypatch, "stop", str(claim.run_dir), "-w", str(project)) == 0
    with pytest.raises(NothingThereError, match="does not exist"):
        hmp.stop(str(project / "runs" / "ghost"), workspace=project)
