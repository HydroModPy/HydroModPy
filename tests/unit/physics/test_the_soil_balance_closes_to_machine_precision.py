"""The soil reservoir closes its water balance to machine precision.

Spec section 7 proves the identity ``P = etr + recharge + runoff +
g*(S'-S) + g*(R'-R)`` term by term; this test measures how close float64
arithmetic keeps that promise over a long run, four parameter sets, and
columns of zero capacity.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    balance_residual,
    full_soil,
    run_soil_balance,
)
from tests._helpers.tolerances import tol

_PARAMETER_SETS = (
    (0.6, 1.0, 0.0, 0.0, 0.0),
    (0.5, 1.2, 0.2, 0.1, 5.0),
    (1.0, 0.0, 0.3, 0.0, 30.0),
    (0.6, 1.0, 0.0, 0.0, 0.2),
)


def _synthetic_forcing() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    n_days, n_columns = 3650, 100
    wet = rng.random((n_days, n_columns)) < 0.45
    precipitation = np.where(wet, rng.gamma(0.8, 6.0, (n_days, n_columns)), 0.0)
    day_of_year = np.arange(n_days) % 365
    seasonal_etp = np.clip(2.0 + 1.8 * np.sin(2 * np.pi * (day_of_year - 100) / 365), 0.0, None)
    etp = np.broadcast_to(seasonal_etp[:, np.newaxis], (n_days, n_columns)).copy()
    ru_mm = rng.uniform(0.0, 300.0, n_columns)
    ru_mm[:3] = 0.0
    return precipitation, etp, ru_mm


def test_the_balance_closes_to_machine_precision() -> None:
    precipitation, etp, ru_mm = _synthetic_forcing()
    worst_cumulative_relative = 0.0
    worst_daily_relative = 0.0

    for alpha, kc, impervious_fraction, bypass_fraction, transit_time_days in _PARAMETER_SETS:
        params = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
        )
        fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
        residual = balance_residual(precipitation, fluxes)

        cumulative_relative = np.max(np.abs(residual.sum(axis=0)) / precipitation.sum(axis=0))
        daily_relative = np.max(np.abs(residual)) / precipitation.max()
        worst_cumulative_relative = max(worst_cumulative_relative, cumulative_relative)
        worst_daily_relative = max(worst_daily_relative, daily_relative)

    tolerance = tol("soil_reservoir_kernel_balance")
    assert worst_cumulative_relative < tolerance
    assert worst_daily_relative < tolerance
