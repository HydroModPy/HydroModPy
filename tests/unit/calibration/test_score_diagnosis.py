"""A metric left undefined has to say what about its series made it so.

An infinite cost sends the reader looking at the metric, which is almost never
where the problem is. Three different causes produce it, and they call for
three different answers: a constant record, a non-finite sample that survived
the alignment, and a genuine numerical blow-up. The trial fails on the
infinite cost; the block says why in the log, once.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.observable_scoring import StationBlockScorer
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.optim.objective import non_finite_diagnosis
from hydromodpy.core.contracts.observables import ObservableResult

INDEX = pd.date_range("2001-01-01", periods=12, freq="MS")
# A monthly run stamps each month at its end, the record at its start.
SIM_INDEX = pd.date_range("2001-02-01", periods=12, freq="MS")


def _score(observed_values, simulated_values, metric: str) -> float:
    scorer = StationBlockScorer(
        "discharge",
        metric,
        [ObservedSeries("G", "discharge", pd.Series(np.asarray(observed_values), index=INDEX))],
    )
    cost, _ = scorer.score(
        {"G": ObservableResult("G", np.asarray(simulated_values, dtype=float), "-", SIM_INDEX)}
    )
    return cost


def test_a_constant_record_names_itself(caplog) -> None:
    # Every efficiency divides by the spread of the observations, so a flat
    # record is undefined however good the simulation is.
    with caplog.at_level("WARNING"):
        cost = _score(np.full(12, 2.5), np.linspace(2.0, 3.0, 12), "nse")

    assert cost == float("inf")
    said = [record.getMessage() for record in caplog.records if "all 2.5" in record.getMessage()]
    assert len(said) == 1
    assert "divides by their spread" in said[0]
    assert "12 observed samples" in said[0]


def test_a_healthy_pair_scores_without_a_diagnosis(caplog) -> None:
    observed = [1.0, 1.4, 2.2, 3.1, 2.0, 1.5, 1.2, 1.0, 0.9, 1.1, 1.6, 2.4]

    with caplog.at_level("WARNING"):
        cost = _score(observed, np.asarray(observed) * 1.3, "nse_log")

    assert np.isfinite(cost)
    assert not [record for record in caplog.records if "undefined" in record.getMessage()]


def test_a_non_finite_sample_is_counted_on_the_side_it_came_from() -> None:
    message = non_finite_diagnosis(np.array([1.0, np.nan, 3.0]), np.array([1.0, 2.0, np.inf]))

    assert "1 of 3 observed" in message
    assert "1 of 3 simulated" in message


def test_the_fallback_reports_both_ranges() -> None:
    # A metric can go non-finite without either cause above; the message then
    # hands the reader the two ranges rather than nothing.
    message = non_finite_diagnosis(np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]))

    assert "3 sample(s) scored" in message
    assert "[1, 3]" in message
    assert "[4, 6]" in message
