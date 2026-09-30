"""A 50 mm pulse through the transit store follows the closed-form exponential reservoir.

Section 7 gives the closed form for a linear reservoir of constant ``k`` fed
one pulse and nothing after: ``Q(0) = 50(1 - k a)``,
``Q(t>=1) = 50 k a^2 exp(-(t-1)/k)`` with ``a = 1 - exp(-1/k)``. Checked
directly on ``route_linear_reservoir`` and through the full soil balance with
a saturated soil, so the pulse crosses it untouched.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    route_linear_reservoir,
    run_soil_balance,
)
from tests._helpers.tolerances import tol

_TRANSIT_TIMES_DAYS = (0.5, 2.0, 5.0, 20.0, 30.0)


def _closed_form(transit_time_days: float, n_days: int) -> np.ndarray:
    k = transit_time_days
    a = 1.0 - np.exp(-1.0 / k)
    t = np.arange(n_days)
    return np.where(t == 0, 50.0 * (1.0 - k * a), 50.0 * k * a * a * np.exp(-(t - 1) / k))


@pytest.mark.parametrize("transit_time_days", _TRANSIT_TIMES_DAYS)
def test_route_linear_reservoir_matches_the_exponential_reservoir(
    transit_time_days: float,
) -> None:
    n_days = int(60 * transit_time_days) + 10
    transit_mm = np.zeros(1)
    outflow = np.empty(n_days)
    for t in range(n_days):
        inflow = np.array([50.0 if t == 0 else 0.0])
        day_outflow, transit_mm = route_linear_reservoir(inflow, transit_mm, transit_time_days)
        outflow[t] = day_outflow[0]

    expected = _closed_form(transit_time_days, n_days)
    max_error = tol(
        "soil_transit_store_impulse__max_absolute_error_against_q_0_50_1_k_a_q_t_1_50_k_a_2_exp_t_1_k_mm"
    )
    volume_error = tol("soil_transit_store_impulse_volume")
    assert np.max(np.abs(outflow - expected)) < max_error
    assert abs(outflow.sum() - 50.0) < volume_error


@pytest.mark.parametrize("transit_time_days", _TRANSIT_TIMES_DAYS)
def test_run_soil_balance_routes_the_impulse_the_same_way(transit_time_days: float) -> None:
    n_days = int(60 * transit_time_days) + 10
    precipitation = np.zeros((n_days, 1))
    precipitation[0, 0] = 50.0
    etp = np.zeros((n_days, 1))
    params = SoilParameters(
        ru_mm=np.array([100.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=transit_time_days,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    expected = _closed_form(transit_time_days, n_days)
    max_error = tol(
        "soil_transit_store_impulse__max_absolute_error_against_q_0_50_1_k_a_q_t_1_50_k_a_2_exp_t_1_k_mm"
    )
    assert np.max(np.abs(fluxes.recharge[:, 0] - expected)) < max_error
