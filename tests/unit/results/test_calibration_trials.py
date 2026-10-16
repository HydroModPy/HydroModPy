"""The trials of the session a run was promoted from are read off the disk.

A run names its session by id in ``lineage.session_id``; the reader finds
``sessions/<case>/`` by that id under the project root the run directory sits
in, and returns the journal as the frame the figures read. A run-shaped
adapter that carries its rows itself is read as before.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext
from hydromodpy.results.calibration_trials import (
    calibration_sessions,
    calibration_trials,
    session_dir_of,
)
from hydromodpy.results.lineage import Lineage

SESSION_ID = "22222222222222222222222222222222"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    session_dir = root / "sessions" / "calage"
    session_dir.mkdir(parents=True)
    (session_dir / "config.toml").write_text(
        '[calibration]\nvariable = "discharge"\nmethod = "grid"\n', encoding="utf-8"
    )
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id=SESSION_ID,
        case_id="calage",
        site="nancon",
        project="demo",
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="grid",
        objective_name="nse",
        search_space={},
        objective_window=None,
    )
    steady = PhaseContext("steady_k", 0, 0)
    transient = PhaseContext("transient_sy", 1, 0)
    persistence.start_phase(steady, frozen={})
    for trial_id, cost in ((1, 0.5), (2, 0.2)):
        persistence.append_iteration(
            ParamSuggestion(trial_id=trial_id, values={"K": 1e-5 * trial_id}),
            EvaluationResult(
                trial_id=trial_id, sim_id=None, objective_value=cost, status="completed"
            ),
            phase=steady,
        )
    persistence.finish_phase("steady_k", status="completed", best=None)
    persistence.start_phase(transient, frozen={"K": {"value": 2e-5, "from": "steady_k"}})
    persistence.append_iteration(
        ParamSuggestion(trial_id=1, values={"Sy": 0.05}),
        EvaluationResult(trial_id=1, sim_id=None, objective_value=0.1, status="completed"),
        phase=transient,
    )
    persistence.link_trial(3, sim_id="9a4f" * 8, rel_dir="runs/calage")
    (root / "runs" / "calage").mkdir(parents=True)
    (root / "sessions" / "calage" / "trials" / "0002").mkdir(parents=True)
    return root


def _run(directory: Path, session_id: str | None = SESSION_ID) -> SimpleNamespace:
    return SimpleNamespace(dir=directory, lineage=Lineage(session_id=session_id))


def test_a_promoted_run_reads_the_whole_session_it_came_from(project) -> None:
    frame = calibration_trials(_run(project / "runs" / "calage"))

    assert list(frame["iteration"]) == [1, 2, 3]
    assert list(frame["phase"]) == ["steady_k", "steady_k", "transient_sy"]
    assert set(frame["session_id"]) == {SESSION_ID}
    assert frame["parameters"][0] == {"K": {"value": 1e-5}}
    assert frame["objective_value"][2] == 0.1
    assert frame["rel_dir"][2] == "runs/calage"


def test_the_session_directory_is_found_by_the_id_the_run_names(project) -> None:
    assert session_dir_of(_run(project / "runs" / "calage")) == project / "sessions" / "calage"
    assert session_dir_of(_run(project / "runs" / "calage", "f" * 32)) is None
    assert session_dir_of(_run(project / "runs" / "calage", None)) is None


def test_a_kept_trial_is_in_its_own_session(project) -> None:
    trial_dir = project / "sessions" / "calage" / "trials" / "0002"

    assert session_dir_of(_run(trial_dir, None)) == project / "sessions" / "calage"
    assert len(calibration_trials(_run(trial_dir, None))) == 3


def test_a_phase_filter_keeps_only_that_phase(project) -> None:
    frame = calibration_trials(_run(project / "runs" / "calage"), phase="steady_k")

    assert list(frame["iteration"]) == [1, 2]
    with pytest.raises(ValueError, match="no trial recorded"):
        calibration_trials(_run(project / "runs" / "calage"), phase="nowhere")


def test_a_run_shaped_adapter_is_read_from_its_own_rows() -> None:
    # The calibration report builds one of these from a session journal, with
    # no project behind it; both carriers resolve to the same frame.
    class _Adapter:
        calibration_iterations = [{"iteration": 0, "objective_value": 1.0}]

    frame = calibration_trials(_Adapter())
    assert list(frame["iteration"]) == [0]


def test_anything_else_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="no calibration trial can be read"):
        calibration_trials(object())


def test_the_sessions_frame_has_one_row_per_phase(project) -> None:
    frame = calibration_sessions(_run(project / "runs" / "calage"))

    assert list(frame["phase_name"]) == ["steady_k", "transient_sy"]
    assert list(frame["phase_index"]) == [0, 1]
    assert set(frame["session_id"]) == {SESSION_ID}
    assert frame["config"][0] == {"variable": "discharge", "method": "grid"}
    assert frame["frozen"][1] == {"K": {"value": 2e-5, "from": "steady_k"}}
    assert list(frame["status"]) == ["completed", "running"]


def test_a_run_without_a_session_has_no_session_rows(project) -> None:
    assert calibration_sessions(_run(project / "runs" / "calage", None)).empty
    assert calibration_sessions(object()).empty
