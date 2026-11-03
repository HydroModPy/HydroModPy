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
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.cli_runner import promote_and_close
from hydromodpy.calibration.runners.promotion import _point_best_if_better, select_trials_to_promote
from tests._helpers.session_documents import session_opening

pytestmark = pytest.mark.unit


@pytest.fixture
def persistence(tmp_path: Path) -> CalibrationPersistence:
    session_dir = tmp_path / "sessions" / "calage"
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(**session_opening("calage", method="scipy_nelder_mead"))
    for trial_id, (cost, speculative) in enumerate(((0.3, False), (0.1, True), (0.2, False)), 1):
        persistence.append_iteration(
            ParamSuggestion(trial_id=trial_id, values={"K": 1e-5 * trial_id}),
            EvaluationResult(
                trial_id=trial_id,
                sim_id=None,
                cost=cost,
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


class TestATieOnTheCost:
    """A bisection answers inside its last bracket, and two trials may share one cost."""

    @pytest.fixture
    def tied(self, tmp_path: Path) -> CalibrationPersistence:
        session_dir = tmp_path / "sessions" / "tie"
        session_dir.mkdir(parents=True)
        persistence = CalibrationPersistence(session_dir)
        persistence.start_session(**session_opening("tie", method="bisection"))
        for trial_id, cost in enumerate((0.3, 0.1, 0.2, 0.1), 1):
            persistence.append_iteration(
                ParamSuggestion(trial_id=trial_id, values={"K": 1e-5 * trial_id}),
                EvaluationResult(trial_id=trial_id, sim_id=None, cost=cost, status="completed"),
            )
        return persistence

    @pytest.mark.parametrize("save_runs", ["best_n", "all"])
    def test_the_run_promoted_first_is_the_trial_the_search_answered(self, tied, save_runs) -> None:
        cfg = SimpleNamespace(save_runs=save_runs, save_best_n=1)

        rows = select_trials_to_promote(cfg, tied, DEFAULT_PHASE, answered=4)

        assert rows[0]["trial"] == 4

    def test_without_an_answer_the_smaller_number_keeps_the_tie(self, tied) -> None:
        cfg = SimpleNamespace(save_runs="best_n", save_best_n=2)

        rows = select_trials_to_promote(cfg, tied, DEFAULT_PHASE)

        assert [row["trial"] for row in rows] == [2, 4]

    def test_an_answer_out_of_the_ranking_changes_nothing(self, tied) -> None:
        rows = tied.top_n(1, DEFAULT_PHASE, answered=99)

        assert [row["trial"] for row in rows] == [2]

    def test_the_session_points_at_the_answer(self, tied, tmp_path) -> None:
        report = CalibrationReport(
            session_id=tied.descriptor.session_id,
            method="bisection",
            n_trials=4,
            best_cost=0.1,
            best_trial=4,
            duration_s=0.0,
            save_runs="none",
            promoted=0,
            workspace=tmp_path,
            session_dir=tied.directory,
        )

        promote_and_close(
            cfg=SimpleNamespace(save_runs="none"),
            trial_ctx=None,
            persistence=tied,
            project_root=tmp_path,
            report=report,
            phase=DEFAULT_PHASE,
            status="completed",
        )

        assert tied.descriptor.best.trial == 4

    def test_a_replay_from_the_cache_answers_with_the_trial_that_solved_it(self, tied) -> None:
        """A resumed search reads a point again under a new number: the run is the first one."""
        tied.append_iteration(
            ParamSuggestion(trial_id=5, values={"K": 1e-5 * 4}),
            EvaluationResult(trial_id=5, sim_id=None, cost=0.1, status="completed"),
        )
        cfg = SimpleNamespace(save_runs="best_n", save_best_n=1)

        rows = select_trials_to_promote(cfg, tied, DEFAULT_PHASE, answered=5)

        assert rows[0]["trial"] == 4

    def test_a_later_promotion_of_the_answer_updates_the_pointer(self, tied) -> None:
        tied.set_best(tied.best_pointer(tied.trial_line(4)))
        linked = tied.link_trial(4, sim_id="s4", rel_dir="runs/tie")

        _point_best_if_better(tied, linked)

        assert tied.descriptor.best.cases[tied.case_id].sim_id == "s4"
