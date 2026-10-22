"""The run promoted to ``runs/<case>`` is the trial the session reports.

A parallel simplex solves candidates its rules never read, and the journal
marks them ``speculative_unused``. One of them can score lower than the point
the search froze. ``session.json`` already skipped it; the selection of the
trials to promote ranks the same way, so the calibrated run and the reported
best are one trial.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import DEFAULT_PHASE, CalibrationPersistence
from hydromodpy.calibration.runners.promotion import select_trials_to_promote
from hydromodpy.results.metric_rule import DateWindow

pytestmark = pytest.mark.unit


@pytest.fixture
def persistence(tmp_path: Path) -> CalibrationPersistence:
    session_dir = tmp_path / "sessions" / "calage"
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id="a" * 32,
        case_id="calage",
        site=None,
        project="demo",
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="scipy_nelder_mead",
        objective_name="nse",
        search_space={"K": {"bounds": [1e-6, 1e-3]}},
        objective_window=DateWindow(start="2001-01-01", end="2002-12-31"),
    )
    for trial_id, (cost, speculative) in enumerate(((0.3, False), (0.1, True), (0.2, False)), 1):
        persistence.append_iteration(
            ParamSuggestion(trial_id=trial_id, values={"K": 1e-5 * trial_id}),
            EvaluationResult(
                trial_id=trial_id,
                sim_id=None,
                objective_value=cost,
                status="completed",
                metadata={"speculative_unused": True} if speculative else {},
            ),
        )
    return persistence


def test_the_best_trial_skips_a_speculative_one(persistence) -> None:
    best = persistence.best_trial()

    assert best is not None
    assert best.trial == 3


def test_the_best_n_promote_the_trial_the_session_reports_first(persistence) -> None:
    rows = select_trials_to_promote(
        SimpleNamespace(save_runs="best_n", save_best_n=2), persistence, DEFAULT_PHASE
    )

    assert [row["trial"] for row in rows] == [3, 1]


def test_keeping_every_trial_still_promotes_the_reported_best_first(persistence) -> None:
    rows = select_trials_to_promote(SimpleNamespace(save_runs="all"), persistence, DEFAULT_PHASE)

    assert [row["trial"] for row in rows] == [3, 1, 2]
