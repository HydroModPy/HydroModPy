"""The cost a calibration minimizes is the score its promoted run is ranked on.

The same series, the same declared window: the calibration scores it while it
searches, and the run promoted from it is scored again by
:mod:`hydromodpy.results.fit_metrics` once sealed. Nothing tied the two: the
promotion tests use a stand-in, and ``fit_metrics`` was imported by its own
tests only.

They used to disagree (N1 of the audit of 2026-10-20). The session kept the
pairs whose END stamp fell in ``[start, end]``; the run keeps the periods
lying wholly in the window. On a monthly run and a 2001-2002 window the
session scored December 2000 to November 2002, the run January 2001 to
December 2002, 24 periods each. Both now read the window through
:func:`~hydromodpy.core.time.period_aggregation.periods_in_window`
(decision m01), and the cost is ``1 - NSE`` of the run to
:data:`SAME_PAIRS`.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.criteria.series import METRICS, SeriesCriterion
from hydromodpy.calibration.metrics.observable_scoring import StationBlockScorer
from hydromodpy.calibration.metrics.observed_pairing import pair_outputs_with_observations
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.results.fit_metrics import score_timeseries
from hydromodpy.results.metric_rule import DateWindow, MetricRule
from tests._helpers.tolerances import tol

GAUGE = "NANCON"
FIRST_PERIOD = pd.Timestamp("2000-01-01")
# Each stamp closes the month before it, as a monthly run stamps its periods.
STAMPS = pd.date_range("2000-02-01", periods=36, freq="MS")
WINDOW = (datetime.date(2001, 1, 1), datetime.date(2002, 12, 31))

SAME_PAIRS = tol("session_cost_against_run_score__gap_of_1_cost_to_the_run_nse")
"""Same pairs, same kernel: machine epsilon (tests/TOLERANCES.md row 179)."""


def _series() -> tuple[pd.Series, pd.Series]:
    """A monthly simulated discharge and the daily record it is judged against."""
    days = pd.date_range(FIRST_PERIOD, STAMPS[-1] - pd.Timedelta(1, unit="D"), freq="D")
    t = np.arange(days.size, dtype=float)
    observed = pd.Series(
        1.0 + 0.6 * np.cos(2.0 * np.pi * t / 365.25) + 0.2 * np.sin(t / 17.0), index=days
    )
    monthly = observed.resample("MS").mean()
    simulated = pd.Series(
        monthly.to_numpy() * 1.15 + 0.1 * np.cos(np.arange(monthly.size)), index=STAMPS
    )
    return observed, simulated


def _run_score() -> tuple[float, int]:
    observed, simulated = _series()
    frame = pd.concat(
        [
            pd.DataFrame(
                {
                    "station_id": GAUGE,
                    "variable": "discharge",
                    "source": "simulated",
                    "time": simulated.index,
                    "value": simulated.to_numpy(),
                }
            ),
            pd.DataFrame(
                {
                    "station_id": GAUGE,
                    "variable": "discharge",
                    "source": "observed",
                    "time": observed.index,
                    "value": observed.to_numpy(),
                }
            ),
        ],
        ignore_index=True,
    )
    rule = MetricRule(station=GAUGE, window=DateWindow(start=WINDOW[0], end=WINDOW[1]))
    scores = score_timeseries(frame, rule=rule, period_start=FIRST_PERIOD)
    return float(scores.score.value), int(scores.score.n_samples)


def _bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(WINDOW[0]), pd.Timestamp(WINDOW[1])


def test_the_run_scores_the_window_on_whole_periods() -> None:
    value, n = _run_score()

    assert np.isfinite(value)
    assert n == 24


def test_variable_and_objective_score_what_the_run_scores() -> None:
    observed, simulated = _series()
    scorer = StationBlockScorer(
        "discharge", "nse", [ObservedSeries(GAUGE, "discharge", observed)], scoring_window=_bounds()
    )

    cost, _ = scorer.score(
        {GAUGE: ObservableResult(GAUGE, simulated.to_numpy(), "m3/s", STAMPS)},
        boundaries=[FIRST_PERIOD, *STAMPS],
    )

    value, _ = _run_score()
    assert 1.0 - cost == pytest.approx(value, abs=SAME_PAIRS)


def test_the_block_route_scores_what_the_run_scores() -> None:
    observed, simulated = _series()
    paired = pair_outputs_with_observations(
        observed={"hydrograph": observed},
        simulated={"hydrograph": simulated},
        scoring_window=_bounds(),
        time_methods={"hydrograph": "mean"},
        period_starts={"hydrograph": FIRST_PERIOD},
    )

    result = SeriesCriterion("nse", METRICS["nse"]).score(
        paired.simulated["hydrograph"], paired.observed["hydrograph"]
    )

    value, n = _run_score()
    assert paired.n_paired["hydrograph"] == n
    assert 1.0 - result.cost == pytest.approx(value, abs=SAME_PAIRS)
