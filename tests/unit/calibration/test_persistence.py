"""The journal of a session is written as the search goes, and read back whole.

No index anywhere: ``CalibrationPersistence`` writes ``session.json``,
``outcome.json``, ``trials.jsonl`` and ``phases/<phase>/session.json`` under
one session directory, and reads them back for the promotion and the report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import (
    CalibrationPersistence,
    PhaseContext,
    best_pointer,
)
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.journal import read_trials, trials_path
from hydromodpy.results.session.phase import read_phase

pytestmark = pytest.mark.unit


def _open(tmp_path: Path, name: str = "calage") -> CalibrationPersistence:
    session_dir = tmp_path / "sessions" / name
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id="a" * 32,
        case_id=name,
        site="nancon",
        project="demo",
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="grid",
        objective_name="nse",
        search_space={"K": {"bounds": [1e-6, 1e-3]}},
        objective_window=DateWindow(start="2001-01-01", end="2002-12-31"),
    )
    return persistence


def _result(trial_id: int, cost: float, **kwargs) -> EvaluationResult:
    payload = {"trial_id": trial_id, "sim_id": None, "objective_value": cost, "status": "completed"}
    payload.update(kwargs)
    return EvaluationResult(**payload)


def _suggestion(trial_id: int, k: float) -> ParamSuggestion:
    return ParamSuggestion(trial_id=trial_id, values={"K": k})


class TestTheSessionOpensAndCloses:
    def test_the_opening_writes_a_running_descriptor_and_outcome(self, tmp_path) -> None:
        persistence = _open(tmp_path)

        descriptor = read_session(persistence.directory)
        assert descriptor.status == "running"
        assert descriptor.case_id == "calage"
        assert descriptor.site == "nancon"
        assert descriptor.objective_window == DateWindow(start="2001-01-01", end="2002-12-31")
        outcome = read_outcome(persistence.directory)
        assert outcome is not None
        assert (outcome.status, outcome.case_id, outcome.project) == ("running", "calage", "demo")
        assert outcome.written_by == "worker"

    def test_the_closing_writes_the_status_the_best_and_the_outcome(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        persistence.append_iteration(_suggestion(1, 1e-4), _result(1, 0.4))
        persistence.append_iteration(_suggestion(2, 2e-4), _result(2, 0.1))

        persistence.finalize_session(
            status="completed",
            best=best_pointer(persistence.best_trial()),
            root_search={"bracket": {"low": 1.0}},
        )

        descriptor = read_session(persistence.directory)
        assert descriptor.status == "completed"
        assert descriptor.ended_at is not None
        assert descriptor.best is not None
        assert (descriptor.best.trial, descriptor.best.objective) == (2, 0.1)
        assert descriptor.root_search == {"bracket": {"low": 1.0}}
        outcome = read_outcome(persistence.directory)
        assert outcome is not None and outcome.status == "completed"

    def test_a_failed_closing_carries_its_error(self, tmp_path) -> None:
        persistence = _open(tmp_path)

        persistence.finalize_session(status="failed", best=None, error="boom")

        assert read_session(persistence.directory).error_message == "boom"
        outcome = read_outcome(persistence.directory)
        assert outcome is not None
        assert outcome.status == "failed"
        assert outcome.error is not None and outcome.error.message == "boom"

    def test_an_aborted_closing_is_an_aborted_outcome(self, tmp_path) -> None:
        persistence = _open(tmp_path)

        persistence.finalize_session(status="aborted", best=None, error="SIGTERM")

        outcome = read_outcome(persistence.directory)
        assert outcome is not None and outcome.status == "aborted"

    def test_a_reopened_session_runs_again_and_keeps_its_trials(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        persistence.append_iteration(_suggestion(1, 1e-4), _result(1, 0.4))
        persistence.finalize_session(status="partial", best=None, error="cut")

        reopened = CalibrationPersistence(persistence.directory)
        reopened.resume_session()

        descriptor = read_session(persistence.directory)
        assert (descriptor.status, descriptor.ended_at, descriptor.error_message) == (
            "running",
            None,
            None,
        )
        assert [line.trial for line in reopened.trials()] == [1]
        line = reopened.append_iteration(_suggestion(1, 3e-4), _result(1, 0.2))
        assert line.trial == 2, "the numbering goes on from the highest trial journaled"


ROOTS = {
    "parameter": "K",
    "minimal": {"k_star": 3.0e-6, "low": 2.9e-6, "high": 3.1e-6, "weight": 0.5},
    "maximal": {"k_star": 2.0e-4, "low": 1.9e-4, "high": 2.1e-4, "weight": 0.5},
    "delta_log10": 1.82,
    "value": 2.4e-5,
    "combined_trial_id": 23,
    "closed": True,
}


class TestTheRootSearchOutlivesTheRun:
    """A root search's bracket and two roots are kept in ``session.json``."""

    def test_the_descriptor_keeps_the_two_roots(self, tmp_path) -> None:
        persistence = _open(tmp_path)

        persistence.finalize_session(status="completed", best=None, root_search={"roots": ROOTS})

        assert read_session(persistence.directory).root_search == {"roots": ROOTS}
        payload = json.loads((persistence.directory / "session.json").read_text())
        assert payload["root_search"]["roots"]["minimal"]["k_star"] == pytest.approx(3.0e-6)

    def test_any_other_search_keeps_no_root_search(self, tmp_path) -> None:
        persistence = _open(tmp_path)

        persistence.finalize_session(status="completed", best=None)

        assert read_session(persistence.directory).root_search is None

    def test_the_close_of_a_search_hands_the_roots_of_its_report_to_the_descriptor(
        self, tmp_path
    ) -> None:
        from hydromodpy.calibration.config import CalibrationConfig
        from hydromodpy.calibration.report import CalibrationReport
        from hydromodpy.calibration.runners.cli_runner import promote_and_close

        persistence = _open(tmp_path)
        persistence.append_iteration(_suggestion(1, 1e-4), _result(1, 0.4))
        report = CalibrationReport(
            session_id="a" * 32,
            method="bisection",
            n_iterations=1,
            best_objective=0.4,
            best_sim_id=None,
            duration_s=1.0,
            save_runs="none",
            promoted=0,
            workspace=tmp_path,
            session_dir=persistence.directory,
            extra={"search_status": "completed", "bracket": {"low": 1.0}, "roots": ROOTS},
        )

        promote_and_close(
            cfg=CalibrationConfig(save_runs="none"),
            trial_ctx=None,
            persistence=persistence,
            project_root=tmp_path,
            report=report,
            phase="main",
            status="completed",
            root_search={key: report.extra[key] for key in ("bracket", "roots")},
        )

        descriptor = read_session(persistence.directory)
        assert descriptor.status == "completed"
        assert descriptor.root_search == {"bracket": {"low": 1.0}, "roots": ROOTS}


class TestTheTrialNumbering:
    def test_the_number_is_unique_across_phases_and_restarts(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        steady = PhaseContext("steady_k", 0, 0)
        transient = PhaseContext("transient_sy", 1, 0)
        again = PhaseContext("transient_sy", 1, 1)

        numbers = [
            persistence.append_iteration(_suggestion(0, 1e-4), _result(0, 0.4), phase=steady).trial,
            persistence.append_iteration(_suggestion(1, 2e-4), _result(1, 0.3), phase=steady).trial,
            persistence.append_iteration(
                _suggestion(0, 0.05), _result(0, 0.2), phase=transient
            ).trial,
            persistence.append_iteration(_suggestion(0, 0.07), _result(0, 0.1), phase=again).trial,
        ]

        assert numbers == [1, 2, 3, 4]
        trials = read_trials(persistence.directory)
        assert [(t.phase, t.restart) for t in trials] == [
            ("steady_k", 0),
            ("steady_k", 0),
            ("transient_sy", 0),
            ("transient_sy", 1),
        ]
        assert persistence.trial_number(0, transient) == 3
        assert persistence.trial_number(0, again) == 4

    def test_the_number_is_given_before_the_trial_runs_and_kept_at_its_line(self, tmp_path) -> None:
        """The sandbox and the kept solve of a trial carry the number of its journal line."""
        persistence = _open(tmp_path)
        steady = PhaseContext("steady_k", 0, 0)

        given = [persistence.assign_trial_number(engine_id, steady) for engine_id in (0, 1)]
        line = persistence.append_iteration(_suggestion(1, 2e-4), _result(1, 0.3), phase=steady)

        assert given == [1, 2]
        assert line.trial == 2
        assert persistence.assign_trial_number(1, steady) == 2, "given once"
        assert persistence.trial_number(0, steady) == 1

    def test_an_engine_trial_written_twice_keeps_its_number(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        first = persistence.append_iteration(_suggestion(3, 1e-4), _result(3, 0.4))
        second = persistence.append_iteration(_suggestion(3, 1e-4), _result(3, 0.2))

        assert first.trial == second.trial == 1
        assert [line.objective for line in read_trials(persistence.directory)] == [0.2]

    def test_a_cached_result_is_a_completed_trial_from_the_cache(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        line = persistence.append_iteration(
            _suggestion(1, 1e-4), _result(1, 0.4, status="cached", from_cache=True)
        )

        assert (line.status, line.from_cache) == ("completed", True)

    def test_a_failed_trial_keeps_no_objective_and_names_its_error(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        line = persistence.append_iteration(
            _suggestion(1, 1e-4),
            _result(1, float("nan"), status="crashed", metadata={"error": "mf6 stopped"}),
        )

        assert line.status == "crashed"
        assert line.objective is None
        assert line.metrics["error"] == "mf6 stopped"
        assert persistence.best_trial() is None


class TestWhatIsReadBack:
    def test_top_n_and_the_best_trial_rank_by_objective(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        for trial_id, cost in ((1, 0.9), (2, 0.1), (3, 0.5), (4, float("nan"))):
            status = "completed" if cost == cost else "crashed"
            persistence.append_iteration(
                _suggestion(trial_id, 1e-4), _result(trial_id, cost, status=status)
            )

        assert [row["iteration"] for row in persistence.top_n(2)] == [2, 3]
        best = persistence.best_trial()
        assert best is not None and best.trial == 2
        rows = persistence.load_iterations()
        assert [row["iteration"] for row in rows] == [1, 2, 3, 4]
        assert rows[0]["parameters"] == {"K": {"value": 1e-4}}
        assert rows[3]["objective_value"] is None

    def test_a_linked_trial_rewrites_its_line_with_the_run(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        persistence.append_iteration(_suggestion(1, 1e-4), _result(1, 0.4))

        linked = persistence.link_trial(1, sim_id="9a4f" * 8, rel_dir="runs/calage")

        assert (linked.sim_id, linked.rel_dir) == ("9a4f" * 8, "runs/calage")
        lines = trials_path(persistence.directory).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2, "the last line of a trial wins"
        assert json.loads(lines[-1])["rel_dir"] == "runs/calage"
        assert read_trials(persistence.directory)[0].rel_dir == "runs/calage"

    def test_the_detail_decides_what_a_line_carries(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        result = _result(1, 0.4, components={"rmse": 0.4}, metadata={"block_costs": {"head": 0.5}})

        none = persistence.append_iteration(_suggestion(1, 1e-4), result, detail="none")
        full = persistence.append_iteration(_suggestion(2, 1e-4), result, detail="full")
        summary = persistence.append_iteration(_suggestion(3, 1e-4), result, detail="summary")

        assert none.metrics == {}
        assert full.metrics == {"rmse": 0.4, "block_costs": {"head": 0.5}}
        assert summary.metrics == {"rmse": 0.4}


class TestThePhases:
    def test_a_phase_opens_running_and_closes_with_its_best(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        context = PhaseContext("steady_k", 0, 0)
        persistence.start_phase(context, frozen={})
        persistence.append_iteration(_suggestion(1, 1e-4), _result(1, 0.4), phase=context)
        persistence.append_iteration(_suggestion(2, 2e-4), _result(2, 0.1), phase=context)

        assert read_phase(persistence.directory, "steady_k").status == "running"
        persistence.finish_phase(
            "steady_k", status="completed", best=best_pointer(persistence.best_trial("steady_k"))
        )

        phase = read_phase(persistence.directory, "steady_k")
        assert phase.status == "completed"
        assert phase.best is not None and phase.best.trial == 2
        assert [item.name for item in persistence.phases()] == ["steady_k"]

    def test_a_restarted_phase_keeps_its_id_and_counts_the_restarts(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        first = persistence.start_phase(PhaseContext("sy", 1, 0), frozen={"K": {"value": 6e-6}})
        persistence.append_iteration(
            _suggestion(1, 0.1), _result(1, 0.4), phase=PhaseContext("sy", 1, 0)
        )
        persistence.append_iteration(
            _suggestion(1, 0.2), _result(1, 0.3), phase=PhaseContext("sy", 1, 1)
        )
        again = persistence.start_phase(PhaseContext("sy", 1, 1), frozen={"K": {"value": 6e-6}})

        assert again.phase_id == first.phase_id
        assert again.frozen == {"K": {"value": 6e-6}}
        closed = persistence.finish_phase("sy", status="completed", best=None)
        assert closed.restarts == 1

    def test_the_best_of_a_phase_reads_that_phase_only(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        steady = PhaseContext("steady_k", 0, 0)
        transient = PhaseContext("transient_sy", 1, 0)
        persistence.append_iteration(_suggestion(1, 1e-4), _result(1, 0.9), phase=steady)
        persistence.append_iteration(_suggestion(1, 0.05), _result(1, 0.1), phase=transient)

        best_steady = persistence.best_trial("steady_k")
        assert best_steady is not None and best_steady.trial == 1
        best_all = persistence.best_trial()
        assert best_all is not None and best_all.trial == 2
