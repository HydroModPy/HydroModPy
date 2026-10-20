"""A session window with a start only scores the periods the run scores.

A protocol phase declares ``scoring_window = {start = ...}`` without an end.
The session compared that start with the END stamp of each pair, so it kept
the period closing on the start day as well: 25 months against the 24 the run
scores on example 04 (N1 of the audit of 2026-10-20, RAPPORT §1.3). Both
session routes now read the window as the run does.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, validate_calib_output
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer
from hydromodpy.calibration.metrics.observed_pairing import pair_outputs_with_observations
from hydromodpy.calibration.metrics.scalar import score
from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink
from hydromodpy.core.contracts.observables import ObservableResult

FIRST_PERIOD = pd.Timestamp("2000-01-01")
STAMPS = pd.date_range("2000-02-01", "2003-01-01", freq="MS")
START_ONLY = (pd.Timestamp("2001-01-01"), None)


def _series() -> tuple[pd.Series, pd.Series]:
    days = pd.date_range(FIRST_PERIOD, STAMPS[-1] - pd.Timedelta(1, unit="D"), freq="D")
    t = np.arange(days.size, dtype=float)
    observed = pd.Series(1.0 + 0.5 * np.cos(2.0 * np.pi * t / 365.25), index=days)
    simulated = pd.Series(1.0 + 0.4 * np.cos(np.arange(STAMPS.size) / 2.0), index=STAMPS)
    return observed, simulated


def test_the_block_route_keeps_the_24_months_of_the_run() -> None:
    observed, simulated = _series()

    paired = pair_outputs_with_observations(
        observed={"hydrograph": observed},
        simulated={"hydrograph": simulated},
        scoring_window=START_ONLY,
        time_methods={"hydrograph": "mean"},
        period_starts={"hydrograph": FIRST_PERIOD},
    )

    assert paired.n_paired["hydrograph"] == 24
    # The first period scored is January 2001, which closes on 1 February.
    assert paired.dates["hydrograph"] == (pd.Timestamp("2001-02-01"), pd.Timestamp("2003-01-01"))


def test_the_single_metric_route_keeps_the_24_months_of_the_run() -> None:
    observed, simulated = _series()
    sink = TrialSeriesSink()

    score(
        observed,
        simulated,
        "nse",
        scoring_window=START_ONLY,
        time_method="mean",
        period_start=FIRST_PERIOD,
        series_sink=sink,
        output="discharge",
        station="NANCON",
    )

    times = [pd.Timestamp(row["time"]) for row in sink.drain()]
    assert len(times) == 24
    assert times[0] == pd.Timestamp("2001-02-01")


def test_the_pairs_session_json_records_are_those_of_the_run() -> None:
    # session.json -> objective_samples is read from these components.
    observed, simulated = _series()
    outputs = {
        "q": validate_calib_output(
            dict(variable="discharge", support="boundary", boundary_id="outlet", observes="gauge")
        )
    }
    blocks = [CalibObjectiveBlockDecl(name="flow", metric="nse", uses_outputs=["q"])]
    scorer = ObservableScorer(
        outputs, blocks, observed_records={"q": observed}, scoring_window=START_ONLY
    )
    boundaries = [FIRST_PERIOD, *STAMPS]

    _, components = scorer.score(
        {"q": ObservableResult("q", simulated.to_numpy(), "m3/s", STAMPS)}, boundaries=boundaries
    )

    assert components["q.n_paired"] == 24.0
    assert date.fromordinal(int(components["q.date_start"])) == date(2001, 2, 1)
    assert date.fromordinal(int(components["q.date_end"])) == date(2003, 1, 1)
