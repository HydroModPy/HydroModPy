"""Stress periods of a run (s) from its time grid, and the steady policy of the first period.

A steady flow regime makes every period steady. A transient regime keeps the first period
steady unless the model says otherwise.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.model import ModelTime
from hydromodpy.solver.modflow_grid.discretization_temporal import (
    build_temporal_discretization_from_time_grid,
    resolve_first_period_steady,
)
from tests._helpers.model_factory import make_model


def time_grid(nstp_per_period: int) -> SimpleNamespace:
    return SimpleNamespace(
        period_lengths_seconds=(1.0, 2.0, 3.0), nstp_per_period=nstp_per_period, window=None
    )


def test_steady_regime_makes_every_period_steady():
    result = build_temporal_discretization_from_time_grid(
        time_grid=time_grid(4), flow_regime="steady", first_period_steady=False
    )

    assert result.nper == 3
    np.testing.assert_allclose(result.perlen, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(result.nstp, [4, 4, 4])
    np.testing.assert_array_equal(result.steady, [True, True, True])


def test_transient_regime_defaults_to_a_steady_first_period():
    result = build_temporal_discretization_from_time_grid(
        time_grid=time_grid(1), flow_regime="transient"
    )

    np.testing.assert_array_equal(result.steady, [True, False, False])


@pytest.mark.parametrize("default", [True, False])
def test_without_a_model_the_default_stands(default: bool):
    assert resolve_first_period_steady(default=default) is default
    assert resolve_first_period_steady(model=None, default=default) is default


def test_model_default_is_a_steady_first_period():
    model = make_model(time=ModelTime(grid=None, regime="transient", first_period_steady=True))

    assert resolve_first_period_steady(model=model) is True
    assert resolve_first_period_steady() is True
    assert resolve_first_period_steady(default=False) is False
