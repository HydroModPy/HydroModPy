"""``session.json`` records the pairs the kept cost was scored on.

``objective_window`` is the declared window completed by the dates of the
TOML: 2016-01-01 to 2020-12-31, 1827 days. A daily cost scored on it holds
the 1827 periods lying in it, whose end stamps run from 2016-01-02 to
2021-01-01 (the session read the end stamp before decision m01, and scored
1828 pairs from 2016-01-01). The window stays as
it is, since ``calibrated_by.window`` is read from it to label a run
``evaluated`` (decision m08). Beside it the descriptor now carries, per dated
output, the count and the first and last stamp of the best trial, and the HTML
report prints both.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.report import load_session_report_data
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.reporting.calibration_report import _render_html
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.session.descriptor import ScoredSamples, read_session


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


PROBE_TOML = """
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
scoring_window = { start = "2016-01-01" }

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


@pytest.fixture
def closed_session(tmp_path: Path, daily_probe) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML, encoding="utf-8")
    report = run_calibration_cli(path, workspace=tmp_path, return_report=True)
    return Path(report.session_dir)


def test_the_window_stays_the_declared_one(closed_session: Path) -> None:
    descriptor = read_session(closed_session)

    assert descriptor.objective_window == DateWindow(start=date(2016, 1, 1), end=date(2020, 12, 31))


def test_the_pairs_of_the_best_trial_sit_beside_it(closed_session: Path) -> None:
    descriptor = read_session(closed_session)

    assert descriptor.objective_samples == {
        "hydrograph": ScoredSamples(n=1827, first=date(2016, 1, 2), last=date(2021, 1, 1))
    }


def test_the_html_report_prints_the_window_and_the_pairs(closed_session: Path) -> None:
    page = _render_html(load_session_report_data(closed_session).session, [], [])

    assert (
        "<th>scored on</th><td>hydrograph 1827 pair(s), period ends 2016-01-02 to "
        "2021-01-01, best trial (window 2016-01-01 to 2020-12-31)</td>"
    ) in page
