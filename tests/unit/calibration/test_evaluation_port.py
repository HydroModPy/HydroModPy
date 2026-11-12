"""Evaluators registered through the port, played by ``run_calibration_cli``.

A probe evaluator returns scripted outcomes, and the tests read what the session,
the report and the console recap say about them (trial counts, dates in days).
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.calibration.runners.recap import result_lines
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.summary import session_summary, summary_rows
from hydromodpy.results.session.view import Session

pytestmark = pytest.mark.fast


def calibration_toml(evaluator: str, header: str = "", extra: str = "") -> str:
    """A 3-point grid on K (m/s) scored by the network distance, run by the given evaluator."""
    return f"""{header}
[calibration]
method = "grid"
max_trials = 3
evaluator = "{evaluator}"
use_cache = false
method_options = {{ points_per_dim = 3 }}
{extra}

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


@contextmanager
def registered(probe):
    evaluation_registry.evaluators.register(probe, replace=True)
    try:
        yield probe
    finally:
        evaluation_registry.evaluators.unregister(probe.evaluator_id)


def run_toml(tmp_path: Path, text: str):
    path = tmp_path / "calibration.toml"
    path.write_text(text, encoding="utf-8")
    return run_calibration_cli(path, workspace=tmp_path)


class OneFailureProbe:
    """The second trial fails, the others complete."""

    evaluator_id = "test_one_failure_probe"
    needs_prepared_model = False
    calls = 0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        OneFailureProbe.calls += 1
        if OneFailureProbe.calls == 2:
            return TrialOutcome(
                cost=math.nan, status="failed", duration_s=0.0, error="solver diverged"
            )
        return TrialOutcome(cost=float(request.values["K"]), status="completed", duration_s=0.0)


def test_partial_session_names_failed_trial(tmp_path: Path) -> None:
    OneFailureProbe.calls = 0
    toml = calibration_toml(OneFailureProbe.evaluator_id, extra='save_runs = "none"')

    with registered(OneFailureProbe):
        report = run_toml(tmp_path, toml)

    descriptor = read_session(report.session_dir)
    assert report.extra["search"]["converged"] is True
    assert descriptor.status == "partial"
    assert descriptor.error_message == "1 trial(s) failed: trial 2"


class ScoredSetProbe:
    """Each trial pairs a different count (dates in days); the cost falls as K rises."""

    evaluator_id = "test_scored_set_probe"
    needs_prepared_model = False
    calls = 0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        ScoredSetProbe.calls += 1
        k = float(request.values["K"])
        return TrialOutcome(
            cost=-k,
            status="completed",
            duration_s=0.0,
            components={
                "q.n_paired": float(100 + ScoredSetProbe.calls),
                "q.date_start": float(date(2016, 1, 1).toordinal()),
                "q.date_end": float(date(2021, 1, 1).toordinal()),
                "probe.k": k,
            },
        )


def test_report_pairs_of_best_trial(tmp_path: Path) -> None:
    ScoredSetProbe.calls = 0
    toml = calibration_toml(
        ScoredSetProbe.evaluator_id, extra='window = { start = "2016-01-01", end = "2020-12-31" }'
    )

    with registered(ScoredSetProbe):
        report = run_toml(tmp_path, toml)

    trials = report.trials
    best = trials.loc[trials["cost"].idxmin()]
    assert int(best["trial"]) != 1  # the best is not the first trial
    assert report.extra["cost_samples"] == {
        "q": {
            "n_paired": int(best["components"]["q.n_paired"]),
            "start": "2016-01-01",
            "end": "2021-01-01",
        }
    }
    assert report.extra["cost_window"] == "window 2016-01-01 to 2020-12-31"


def test_recap_prints_pairs_beside_cost() -> None:
    report = CalibrationReport(
        session_id="abc123",
        method="grid",
        n_trials=4,
        best_cost=0.334115,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters={"Sy": 0.045},
        extra={
            "cost_metric": "1 - nse_log",
            "cost_window": "window 2016-01-01 to 2020-12-31",
            "cost_samples": {
                "hydrograph": {"n_paired": 1828, "start": "2016-01-01", "end": "2021-01-01"}
            },
        },
    )

    lines = result_lines(report)

    cost = lines.index("  cost: 0.334115 (1 - nse_log)")
    assert lines[cost + 1] == (
        "  scored on: hydrograph 1828 pair(s), period ends 2016-01-01 to 2021-01-01, "
        "best trial (window 2016-01-01 to 2020-12-31)"
    )


class DailyProbe:
    """Pairs 1827 daily stamps on the best trial, fewer on the others."""

    evaluator_id = "test_daily_scored_set_probe"
    needs_prepared_model = False

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        k = float(request.values["K"])
        best = k > 1e-4
        return TrialOutcome(
            cost=-k,
            status="completed",
            duration_s=0.0,
            components={
                "hydrograph.n_paired": 1827.0 if best else 1700.0,
                "hydrograph.date_start": float(date(2016, 1, 2).toordinal()),
                "hydrograph.date_end": float(date(2021, 1, 1).toordinal()),
            },
        )


def test_html_report_window_and_pairs(tmp_path: Path) -> None:
    toml = calibration_toml(
        DailyProbe.evaluator_id,
        header="[simulation.time]\nstart_datetime = 2015-01-01\nend_datetime = 2020-12-31\n",
        extra='save_runs = "none"\nwindow = { start = "2016-01-01" }',
    )

    with registered(DailyProbe):
        report = run_toml(tmp_path, toml)

    summary = dict(summary_rows(session_summary(Session(Path(report.session_dir)))))
    assert summary["scored on"] == (
        "hydrograph 1827 pair(s), period ends 2016-01-02 to "
        "2021-01-01, best trial (window 2016-01-01 to 2020-12-31)"
    )
