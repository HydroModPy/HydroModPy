"""Tests of `evaluation.port`."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.report import CalibrationReport, load_session_report_data
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.cli.commands import run as run_command
from hydromodpy.cli.commands.calibrate import _format_calibration_result
from hydromodpy.reporting.calibration_report import _render_html
from hydromodpy.results.session.descriptor import ScoredSamples, read_session
from tests._helpers.session_documents import calibration_window

# From test_a_session_partial_for_a_failed_trial_names_it.py
# A session left ``partial`` by a failed trial names that trial.
#
# A search can meet its stopping rule and still close ``partial`` because one
# trial failed. The message written to ``session.json`` then read the name of
# the stopping rule, as if the budget had run out. It now names the failed
# trials, and the stopping rule only when the rule was not met.


class _OneFailureProbe:
    """The second trial fails, the others complete."""

    evaluator_id = "test_one_failure_probe"
    needs_prepared_model = False
    calls = 0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        _OneFailureProbe.calls += 1
        if _OneFailureProbe.calls == 2:
            return TrialOutcome(
                cost=math.nan, status="failed", duration_s=0.0, error="solver diverged"
            )
        return TrialOutcome(cost=float(request.values["K"]), status="completed", duration_s=0.0)


@pytest.fixture
def one_failure_probe():
    _OneFailureProbe.calls = 0
    evaluation_registry.register(_OneFailureProbe, replace=True)
    try:
        yield _OneFailureProbe
    finally:
        evaluation_registry.unregister(_OneFailureProbe.evaluator_id)


PROBE_TOML = """
[calibration]
method = "grid"
max_trials = 3
evaluator = "test_one_failure_probe"
use_cache = false
save_runs = "none"
method_options = { points_per_dim = 3 }

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


def test_the_message_names_the_failed_trial_not_the_rule(tmp_path: Path, one_failure_probe) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML, encoding="utf-8")

    report = run_calibration_cli(path, workspace=tmp_path)

    descriptor = read_session(report.session_dir)
    assert report.extra["search"]["converged"] is True
    assert descriptor.status == "partial"
    assert descriptor.error_message == "1 trial(s) failed: trial 2"


# From test_the_recap_says_what_the_cost_was_scored_on.py
# The console recap of a calibration says what its cost was scored on.
#
# ``hmp calibrate`` and the recap of ``hmp run`` printed the best cost and its
# metric, never the samples behind it: no window, no count. The only dated line
# read the first trial, not the trial whose cost was printed. The report now
# carries the pairs the best trial was scored on (count, first and last period
# end stamp, per output) and the window the search declares, and both recaps
# print them beside the cost.


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


PROBE_TOML__recap_says = """
[calibration]
method = "grid"
max_trials = 3
evaluator = "test_scored_set_probe"
use_cache = false
method_options = { points_per_dim = 3 }
window = { start = "2016-01-01", end = "2020-12-31" }

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


def test_the_report_carries_the_pairs_of_the_best_trial(tmp_path: Path, scored_set_probe) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML__recap_says, encoding="utf-8")

    report = run_calibration_cli(path, workspace=tmp_path)

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


def _report(extra: dict) -> CalibrationReport:
    return CalibrationReport(
        session_id="abc123",
        method="grid",
        n_trials=4,
        best_cost=0.334115,
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
        "n_trials": 4,
        "best_cost": 0.334115,
        "best_parameters": {"Sy": 0.045},
        "extra": SCORED,
    }

    run_command._print_calibration_recap(summary, Path("calibrate.toml"))

    line = capsys.readouterr().err.splitlines()[1]
    assert line.endswith(
        "cost 0.3341 (1 - nse_log) on hydrograph 1828 pair(s), period ends 2016-01-01 to 2021-01-01"
    )


# From test_the_session_records_the_pairs_its_cost_was_scored_on.py
# ``session.json`` records the pairs the kept cost was scored on.
#
# ``windows`` holds the declared window completed by the dates of the
# TOML: 2016-01-01 to 2020-12-31, 1827 days. A daily cost scored on it holds
# the 1827 periods lying in it, whose end stamps run from 2016-01-02 to
# 2021-01-01 (the session read the end stamp before decision m01, and scored
# 1828 pairs from 2016-01-01). The window stays as
# it is, since ``calibrated_by.windows`` is read from it to label a run
# ``evaluated`` (decision m08). Beside it the descriptor now carries, per dated
# output, the count and the first and last stamp of the best trial, and the HTML
# report prints both.


class _DailyProbe:
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


@pytest.fixture
def daily_probe():
    evaluation_registry.register(_DailyProbe, replace=True)
    try:
        yield _DailyProbe
    finally:
        evaluation_registry.unregister(_DailyProbe.evaluator_id)


PROBE_TOML__session_records = """
[simulation.time]
start_datetime = 2015-01-01
end_datetime = 2020-12-31

[calibration]
method = "grid"
max_trials = 3
evaluator = "test_daily_scored_set_probe"
use_cache = false
save_runs = "none"
method_options = { points_per_dim = 3 }
window = { start = "2016-01-01" }

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


@pytest.fixture
def closed_session(tmp_path: Path, daily_probe) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML__session_records, encoding="utf-8")
    report = run_calibration_cli(path, workspace=tmp_path)
    return Path(report.session_dir)


def test_the_window_stays_the_declared_one(closed_session: Path) -> None:
    descriptor = read_session(closed_session)

    assert descriptor.windows == calibration_window(date(2016, 1, 1), date(2020, 12, 31))


def test_the_pairs_of_the_best_trial_sit_beside_it(closed_session: Path) -> None:
    descriptor = read_session(closed_session)

    assert descriptor.scored == [
        ScoredSamples(
            window="calibration",
            case_id="calibration",
            output="hydrograph",
            n=1827,
            first=date(2016, 1, 2),
            last=date(2021, 1, 1),
        )
    ]


def test_the_html_report_prints_the_window_and_the_pairs(closed_session: Path) -> None:
    page = _render_html(load_session_report_data(closed_session).session, [], [])

    assert (
        "<th>scored on</th><td>hydrograph 1827 pair(s), period ends 2016-01-02 to "
        "2021-01-01, best trial (window 2016-01-01 to 2020-12-31)</td>"
    ) in page
