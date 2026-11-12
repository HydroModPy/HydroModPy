"""A calibration session survives on disk: ``sessions/<case>/`` says everything.

Written live by :class:`~hydromodpy.calibration.persistence.CalibrationPersistence`
in the formats of :mod:`hydromodpy.results.session`; read back by anyone with
pyarrow and json. No index is opened to write or to read it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.session_scope import write_session_readme
from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.results.session.descriptor import ParameterBound, find_session_dir
from hydromodpy.results.session.journal import TrialParam, read_trials
from hydromodpy.results.session.trial_series import (
    TRIAL_SERIES_SCHEMA,
    read_trial_series,
    write_trial_series,
)
from hydromodpy.results.storage.contract import SESSION_TRIAL_SERIES_DIRNAME

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


def test_the_last_line_of_a_trial_carries_the_whole_trial(project) -> None:
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


def test_a_session_is_found_by_its_id_in_either_spelling(project) -> None:
    dashed = "3f2a1b7c-9d0e-4f11-8a2b-5c6d7e8f9012"

    assert find_session_dir(project, SESSION_ID) == project / "sessions" / "calage"
    assert find_session_dir(project, dashed) == project / "sessions" / "calage"
    assert find_session_dir(project, "f" * 32) is None


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


def _rewrite_footer(path: Path, footer: dict[str, str] | None) -> None:
    """Replace the footer of a series file, ``None`` dropping every key."""
    table = pq.read_table(path).replace_schema_metadata(footer)
    pq.write_table(table, path)


@pytest.mark.parametrize(
    ("footer", "reads"),
    [
        pytest.param({"hmp.schema_version": TRIAL_SERIES_SCHEMA}, True, id="current"),
        pytest.param(None, True, id="no key, the form of a pre-release, reads as v1"),
        pytest.param({"hmp.schema_version": "hydromodpy.trial_series.v2"}, False, id="newer"),
        pytest.param({"hmp.schema_version": "v3"}, False, id="a table of a run"),
        pytest.param({"hmp.schema_version": "garbage"}, False, id="not a version"),
    ],
)
def test_the_reader_takes_a_missing_key_as_v1_and_refuses_the_rest_by_name(
    tmp_path, footer, reads
) -> None:
    target = write_trial_series(tmp_path, 1, _ROWS)
    _rewrite_footer(target, footer)

    if reads:
        assert read_trial_series(tmp_path)["trial"].tolist() == [1, 1]
        return
    with pytest.raises(SchemaVersionMismatchError) as caught:
        read_trial_series(tmp_path)
    assert "hmp.schema_version" in str(caught.value)
    assert target.name in str(caught.value)
