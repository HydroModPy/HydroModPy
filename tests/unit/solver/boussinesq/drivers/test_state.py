"""Fluxes a stress period exports, from the time steps that make it (m/s and m3/s)."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.drivers.state import PeriodFluxes


def fluxes(value: float) -> PeriodFluxes:
    """One-cell fluxes that are all ``value``."""
    cell = np.asarray([value])
    return PeriodFluxes(**dict.fromkeys(PeriodFluxes.__dataclass_fields__, cell))


def test_period_mean_weighs_steps_by_length() -> None:
    # A step of 1 m3/s over a quarter of the period, then 3 m3/s over the rest.
    mean = PeriodFluxes.period_mean([fluxes(1.0), fluxes(3.0)], [0.25, 0.75])

    np.testing.assert_allclose(mean.drainage_flux_m3_s, [2.5])


REFUSALS = [
    pytest.param([fluxes(1.0)], [0.5, 0.5], "1 steps for 2 weights", id="fewer steps"),
    pytest.param([], [], "0 steps for 0 weights", id="no step"),
]


@pytest.mark.parametrize(("steps", "weights", "message"), REFUSALS)
def test_refusals(steps, weights, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PeriodFluxes.period_mean(steps, weights)
