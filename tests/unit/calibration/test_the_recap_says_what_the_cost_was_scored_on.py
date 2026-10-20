"""The console recap of a calibration says what its cost was scored on.

``hmp calibrate`` and the recap of ``hmp run`` printed the best cost and its
metric, never the samples behind it: no window, no count. The only dated line
read the first trial, not the trial whose cost was printed. The report now
carries the pairs the best trial was scored on (count, first and last period
end stamp, per output) and the window the search declares, and both recaps
print them beside the cost.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.cli.commands import run as run_command
from hydromodpy.cli.commands.calibrate import _format_calibration_result


class _ScoredSetProbe:
    """Each trial pairs a different count; the cost falls as K rises."""

    evaluator_id = "test_scored_set_probe"
    needs_prepared_model = False
    calls = 0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        _ScoredSetProbe.calls += 1
        k = float(request.values["K"])
        n = 100 + _ScoredSetProbe.calls
        return TrialOutcome(
            cost=-k,
            status="completed",
            duration_s=0.0,
            components={
                "q.n_paired": float(n),
                "q.date_start": float(date(2016, 1, 1).toordinal()),
                "q.date_end": float(date(2021, 1, 1).toordinal()),
                "probe.k": k,
            },
        )


@pytest.fixture
def scored_set_probe():
    _ScoredSetProbe.calls = 0
    evaluation_registry.register(_ScoredSetProbe, replace=True)
    try:
        yield _ScoredSetProbe
    finally:
        evaluation_registry.unregister(_ScoredSetProbe.evaluator_id)


PROBE_TOML = """
[calibration]
method = "grid"
max_trials = 3
evaluator = "test_scored_set_probe"
use_cache = false
method_options = { points_per_dim = 3 }
scoring_window = { start = "2016-01-01", end = "2020-12-31" }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def test_the_report_carries_the_pairs_of_the_best_trial(tmp_path: Path, scored_set_probe) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML, encoding="utf-8")

    report = run_calibration_cli(path, workspace=tmp_path, return_report=True)

    trials = report.iterations
    best = trials.loc[trials["objective"].idxmin()]
    assert int(best["trial"]) != 1  # the best is not the first trial
    assert report.extra["cost_samples"] == {
        "q": {
            "n_paired": int(best["metrics"]["q.n_paired"]),
            "start": "2016-01-01",
            "end": "2021-01-01",
        }
    }
    assert report.extra["cost_window"] == "window 2016-01-01 to 2020-12-31"


def _report(extra: dict) -> CalibrationReport:
    return CalibrationReport(
        session_id="abc123",
        method="grid",
        n_iterations=4,
        best_objective=0.334115,
        best_sim_id=None,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters={"Sy": 0.045},
        extra=extra,
    )


SCORED = {
    "cost_metric": "1 - nse_log",
    "cost_window": "window 2016-01-01 to 2020-12-31",
    "cost_samples": {"hydrograph": {"n_paired": 1828, "start": "2016-01-01", "end": "2021-01-01"}},
}


def test_hmp_calibrate_prints_the_pairs_beside_the_cost() -> None:
    lines = _format_calibration_result(_report(SCORED))

    cost = lines.index("  cost: 0.334115 (1 - nse_log)")
    assert lines[cost + 1] == (
        "  scored on: hydrograph 1828 pair(s), period ends 2016-01-01 to 2021-01-01, "
        "best trial (window 2016-01-01 to 2020-12-31)"
    )


def test_hmp_calibrate_prints_the_declared_window_when_no_pair_was_counted() -> None:
    extra = {"cost_metric": "1 - nse_log", "cost_window": "window 2016-01-01 to 2020-12-31"}

    lines = _format_calibration_result(_report(extra))

    assert "  scored on: window 2016-01-01 to 2020-12-31, pairs not counted" in lines


def test_the_hmp_run_recap_prints_the_pairs_beside_the_cost(tmp_path, capsys) -> None:
    summary = {
        "method": "grid",
        "n_iterations": 4,
        "best_objective": 0.334115,
        "best_parameters": {"Sy": 0.045},
        "extra": SCORED,
    }

    run_command._print_calibration_recap(summary, Path("calibrate.toml"))

    line = capsys.readouterr().err.splitlines()[1]
    assert line.endswith(
        "cost 0.3341 (1 - nse_log) on hydrograph 1828 pair(s), period ends 2016-01-01 to 2021-01-01"
    )
