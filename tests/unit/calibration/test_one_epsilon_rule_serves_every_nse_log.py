"""One rule gives the epsilon of nse_log, and the figures and prototypes call it.

The rule (the larger of 1e-9 and one percent of the median positive
observation) was written three times. ``log_floor`` is the one copy.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.observations.natural_observations import discharge_log_nse_cost
from hydromodpy.core.metrics import log_floor, log_nse


def test_the_floor_is_one_percent_of_the_median_positive_observation() -> None:
    assert log_floor([0.0, 2.0, 4.0, np.nan, 100.0]) == pytest.approx(0.04)


def test_the_floor_never_drops_below_the_absolute_minimum() -> None:
    assert log_floor([0.0, 1e-12]) == 1e-9
    assert log_floor([0.0, 0.0]) == pytest.approx(0.01)
    assert log_floor([]) == pytest.approx(0.01)


def test_log_nse_defaults_to_the_floor_of_the_scored_pairs() -> None:
    sim = np.array([1.0, 2.0, 3.0, np.nan, 5.0])
    obs = np.array([1.2, 1.9, 3.3, 900.0, 4.6])

    explicit = log_nse(sim, obs, eps=log_floor(obs[np.isfinite(sim)]))

    assert log_nse(sim, obs) == pytest.approx(explicit)


def test_the_natural_prototype_reports_the_floor_of_the_scored_pairs() -> None:
    sim = np.array([1.0, 2.0, 3.0, np.nan, 5.0])
    obs = np.array([1.2, 1.9, 3.3, 900.0, 4.6])

    cost, diagnostics = discharge_log_nse_cost(sim, obs)

    scored = obs[np.isfinite(sim)]
    assert diagnostics["nse_log_epsilon"] == log_floor(scored)
    assert cost == pytest.approx(1.0 - log_nse(sim, obs, eps=log_floor(scored)))
