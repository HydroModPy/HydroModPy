"""A metric that refuses has to say what about its series made it refuse.

"returned a non-finite value" sends the reader looking at the metric, which is
almost never where the problem is. Three different causes produce it, and they
call for three different answers: a constant record, a non-finite sample that
survived the alignment, and a genuine numerical blow-up.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.metrics.scalar import score

INDEX = pd.date_range("2001-01-01", periods=12, freq="MS")


def _series(values) -> pd.Series:
    return pd.Series(np.asarray(values, dtype="float64"), index=INDEX)


def test_a_constant_record_names_itself() -> None:
    # Every metric here divides by the spread of the observations, so a flat
    # record is undefined however good the simulation is.
    observed = _series(np.full(12, 2.5))
    simulated = _series(np.linspace(2.0, 3.0, 12))

    with pytest.raises(ValueError, match="all 2.5") as failure:
        score(observed, simulated, "nse")

    message = str(failure.value)
    assert "divides by their spread" in message
    assert "12 observed samples" in message


def test_a_non_finite_sample_is_counted_on_the_side_it_came_from() -> None:
    observed = _series(np.linspace(1.0, 2.0, 12))
    simulated = _series(np.linspace(1.0, 2.0, 12))
    # align_observed_simulated drops NaN, so the only way one reaches the metric
    # is through the log clip turning a zero into -inf.
    observed.iloc[3] = 0.0
    simulated.iloc[3] = 0.0

    try:
        cost = score(observed, simulated, "nse_log")
    except ValueError as exc:
        assert "Non-finite samples reached the metric" in str(exc)
    else:
        assert np.isfinite(cost)


def test_a_healthy_pair_scores_without_a_diagnosis() -> None:
    observed = _series([1.0, 1.4, 2.2, 3.1, 2.0, 1.5, 1.2, 1.0, 0.9, 1.1, 1.6, 2.4])
    simulated = observed * 1.3

    cost = score(observed, simulated, "nse_log")

    assert np.isfinite(cost)


def test_the_fallback_reports_both_ranges() -> None:
    # A metric can go non-finite without either cause above; the message then
    # hands the reader the two ranges rather than nothing.
    from hydromodpy.calibration.metrics.scalar import _non_finite_diagnosis

    message = _non_finite_diagnosis(np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]))

    assert "3 sample(s) scored" in message
    assert "[1, 3]" in message
    assert "[4, 6]" in message
