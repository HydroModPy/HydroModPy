"""A calibration session survives on disk: ``sessions/<case>/`` says everything.

Written live by :class:`~hydromodpy.calibration.persistence.CalibrationPersistence`
in the formats of :mod:`hydromodpy.results.session`; read back by anyone with
pyarrow and json. No index is opened to write or to read it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext
from hydromodpy.calibration.runners.cli_runner import write_session_readme
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.session.descriptor import (
    ParameterBound,
    find_session_dir,
    list_session_dirs,
    read_session,
)
from hydromodpy.results.session.journal import TrialParam, read_trials
from hydromodpy.results.session.phase import FrozenValue
from hydromodpy.results.session.trial_series import read_trial_series, write_trial_series
from hydromodpy.results.storage.contract import (
    README_FILENAME,
    RUN_OUTCOME_FILENAME,
    SESSION_DESCRIPTOR_FILENAME,
    SESSION_PHASES_DIRNAME,
    SESSION_TRIAL_SERIES_DIRNAME,
    SESSION_TRIALS_FILENAME,
)

SESSION_ID = "3f2a1b7c9d0e4f118a2b5c6d7e8f9012"


def _session(project: Path, name: str = "calage", session_id: str = SESSION_ID):
    directory = project / "sessions" / name
    directory.mkdir(parents=True)
    persistence = CalibrationPersistence(directory)
    persistence.start_session(
        session_id=session_id,
        case_id=name,
        site="nancon",
        project=project.name,
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="optuna",
        cost_name="rmse",
        bounds={"K_aquifer": ParameterBound(lower=1e-6, upper=1e-3, search_space="log")},
        windows={},
    )
    return persistence


def _trial(number: int, objective: float) -> tuple[ParamSuggestion, EvaluationResult]:
    return (
        ParamSuggestion(trial_id=number, values={"K_aquifer": 1e-4 * (number + 1)}),
        EvaluationResult(
            trial_id=number,
            sim_id=None,
            cost=objective,
            status="completed",
            duration_s=0.5 + number,
            components={"rmse": objective},
            metadata={"params_hash": f"v2:{number:064x}"},
        ),
    )


@pytest.fixture
def project(tmp_path) -> Path:
    """A project whose only content is one finished calibration session."""
    root = tmp_path / "demo"
    root.mkdir()
    persistence = _session(root)
    for number, objective in enumerate((0.42, 0.19, 0.31)):
        persistence.append_iteration(*_trial(number, objective))
    persistence.finalize_session(
        status="completed",
        best=persistence.best_pointer(persistence.best_trial()),
        root_search={"roots": {"parameter": "K", "delta_log10": 1.8}},
    )
    write_session_readme(persistence)
    return root


def test_the_session_directory_holds_the_four_documents(project) -> None:
    (directory,) = list_session_dirs(project)

    assert directory == project / "sessions" / "calage"
    for name in (
        SESSION_DESCRIPTOR_FILENAME,
        SESSION_TRIALS_FILENAME,
        RUN_OUTCOME_FILENAME,
        README_FILENAME,
    ):
        assert (directory / name).is_file(), name


def test_the_descriptor_carries_identity_bounds_cost_and_best_trial(project) -> None:
    descriptor = read_session(project / "sessions" / "calage")

    assert descriptor.session_id == SESSION_ID
    assert descriptor.case_id == "calage"
    assert (descriptor.sites, descriptor.only_case, descriptor.only_site) == (
        ["nancon"],
        "calage",
        "nancon",
    )
    assert descriptor.method == "optuna"
    assert descriptor.cost_name == "rmse"
    bound = descriptor.bounds["K_aquifer"]
    assert (bound.lower, bound.upper, bound.search_space) == (1e-6, 1e-3, "log")
    assert descriptor.ended_at is not None and descriptor.started_at <= descriptor.ended_at
    assert descriptor.status == "completed"
    assert descriptor.best is not None
    assert (descriptor.best.trial, descriptor.best.cost) == (2, 0.19)
    assert descriptor.best.cases["calage"].cost == 0.19
    assert descriptor.root_search == {"roots": {"parameter": "K", "delta_log10": 1.8}}


def test_one_line_per_trial_carries_the_whole_trial(project) -> None:
    trials = read_trials(project / "sessions" / "calage")

    assert [t.trial for t in trials] == [1, 2, 3]
    assert [t.cost for t in trials] == [0.42, 0.19, 0.31]
    assert {t.status for t in trials} == {"completed"}
    assert {t.only_case.from_cache for t in trials} == {False}
    assert trials[1].params == {"K_aquifer": TrialParam(value=2e-4)}
    case = trials[1].only_case
    assert (case.cost, case.components, case.status) == (0.19, {"rmse": 0.19}, "completed")
    assert case.params_hash == f"v2:{1:064x}"
    assert (trials[1].ended_at - trials[1].started_at).total_seconds() == pytest.approx(1.5)


def test_the_outcome_is_that_of_a_completed_session(project) -> None:
    outcome = read_outcome(project / "sessions" / "calage")

    assert outcome is not None
    assert (outcome.status, outcome.case_id, outcome.project) == ("completed", "calage", "demo")
    assert outcome.ended_at is not None


def test_the_readme_names_the_case_the_best_trial_and_the_files(project) -> None:
    text = (project / "sessions" / "calage" / README_FILENAME).read_text(encoding="utf-8")

    assert text.startswith("# Calibration calage")
    assert "trial 2, cost 0.19" in text
    assert SESSION_TRIALS_FILENAME in text


def test_an_interrupted_session_keeps_the_trials_it_had_time_to_run(tmp_path) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    persistence = _session(root)
    persistence.append_iteration(*_trial(0, 0.42))

    descriptor = read_session(persistence.directory)

    assert descriptor.status == "running"
    assert descriptor.ended_at is None
    assert [t.trial for t in read_trials(persistence.directory)] == [1]
    outcome = read_outcome(persistence.directory)
    assert outcome is not None and outcome.status == "running"


def test_a_session_is_found_by_its_id_in_either_spelling(project) -> None:
    dashed = "3f2a1b7c-9d0e-4f11-8a2b-5c6d7e8f9012"

    assert find_session_dir(project, SESSION_ID) == project / "sessions" / "calage"
    assert find_session_dir(project, dashed) == project / "sessions" / "calage"
    assert find_session_dir(project, "f" * 32) is None


def test_a_directory_without_a_descriptor_is_not_a_calibration_session(project) -> None:
    (project / "sessions" / "spinup-2026").mkdir()

    assert len(list_session_dirs(project)) == 1


def test_the_phases_of_a_staged_session_sit_under_phases(tmp_path) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    persistence = _session(root)
    steady = PhaseContext("steady_k", 0, 0)
    persistence.start_phase(steady, frozen={})
    persistence.append_iteration(*_trial(0, 0.42), phase=steady)
    persistence.finish_phase(
        "steady_k",
        status="completed",
        best=persistence.best_pointer(persistence.best_trial("steady_k")),
    )
    transient = PhaseContext("transient_sy", 1, 0)
    frozen = FrozenValue(value=1e-4, mode="replace", from_phase="steady_k")
    persistence.start_phase(transient, frozen={"K": frozen})
    persistence.append_iteration(*_trial(0, 0.1), phase=transient)

    phases = persistence.phases()
    assert [(p.name, p.index, p.status) for p in phases] == [
        ("steady_k", 0, "completed"),
        ("transient_sy", 1, "running"),
    ]
    assert phases[1].frozen == {"K": frozen}
    payload = json.loads(
        (persistence.directory / SESSION_PHASES_DIRNAME / "steady_k" / "session.json").read_text()
    )
    assert payload["best"]["trial"] == 1
    assert [t.phase for t in read_trials(persistence.directory)] == ["steady_k", "transient_sy"]


# -- the opt-in trial series table -------------------------------------------


_ROWS = [
    {
        "output": "q",
        "station": "G1",
        "time": pd.Timestamp("2001-01-31"),
        "simulated": 1.1,
        "observed": 1.0,
    },
    {
        "output": "q",
        "station": "G1",
        "time": pd.Timestamp("2001-02-28"),
        "simulated": 2.2,
        "observed": 2.0,
    },
]


def test_the_writer_names_the_file_so_it_sorts_by_trial_number(tmp_path) -> None:
    for trial in (2, 10, 1):
        write_trial_series(tmp_path, trial, _ROWS)

    names = sorted(p.name for p in (tmp_path / SESSION_TRIAL_SERIES_DIRNAME).iterdir())

    assert names == ["trial-000001.parquet", "trial-000002.parquet", "trial-000010.parquet"]


def test_the_writer_produces_the_expected_table(tmp_path) -> None:
    target = write_trial_series(tmp_path, 7, _ROWS)

    table = pd.read_parquet(target)
    assert list(table.columns) == ["trial", "output", "station", "time", "simulated", "observed"]
    assert table["trial"].tolist() == [7, 7]
    assert table["simulated"].tolist() == [1.1, 2.2]


def test_a_trial_with_no_rows_writes_nothing(tmp_path) -> None:
    assert write_trial_series(tmp_path, 3, []) is None
    assert not (tmp_path / SESSION_TRIAL_SERIES_DIRNAME).exists()


def test_the_reader_concatenates_every_trial_and_is_typed_when_empty(tmp_path) -> None:
    assert read_trial_series(tmp_path).empty
    write_trial_series(tmp_path, 1, _ROWS[:1])
    write_trial_series(tmp_path, 2, _ROWS[1:])

    table = read_trial_series(tmp_path)

    assert sorted(table["trial"].tolist()) == [1, 2]
    assert list(table.columns) == ["trial", "output", "station", "time", "simulated", "observed"]
