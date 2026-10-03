"""The water balance still closes once ``runoff_lag`` delays the routed runoff.

Mirrors ``test_the_curve_number_balance_closes_with_routing.py``: the new
``lag_storage`` has to enter ``balance_residual`` for the identity to hold,
daily and summed over each calendar year, exactly as ``cn_storage`` already
does for ``runoff_time``.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    annual_budget,
    balance_residual,
    full_soil,
    run_soil_balance,
)
from tests._helpers.tolerances import tol

_PARAMETER_SETS = (
    (0.6, 1.0, 0.0, 0.0, 2.0, 70.0, 0.0, 0.0),
    (0.6, 1.0, 0.05, 0.1, 5.0, 80.0, 1.0, 0.75),
    (0.5, 1.2, 0.0, 0.0, 0.0, 90.0, 3.5, 4.0),
)


def _synthetic_forcing() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(6)
    n_days, n_columns = 3 * 365, 15
    wet = rng.random((n_days, n_columns)) < 0.45
    precipitation = np.where(wet, rng.gamma(0.8, 8.0, (n_days, n_columns)), 0.0)
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    ru_mm = rng.uniform(20.0, 300.0, n_columns)
    years = 2020 + (np.arange(n_days) // 365)
    return precipitation, etp, ru_mm, years


def test_the_daily_and_annual_balance_close_to_1e_9_with_a_runoff_lag() -> None:
    precipitation, etp, ru_mm, years = _synthetic_forcing()
    weights = np.full(ru_mm.shape[0], 1.0 / ru_mm.shape[0])
    tolerance = tol("soil_curve_number_runoff_balance_with_routing")

    for (
        alpha,
        kc,
        impervious_fraction,
        bypass_fraction,
        transit_time_days,
        curve_number,
        runoff_time_days,
        runoff_lag_days,
    ) in _PARAMETER_SETS:
        params = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
            curve_number=curve_number,
            runoff_time_days=runoff_time_days,
            runoff_lag_days=runoff_lag_days,
        )
        fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
        daily_residual = balance_residual(precipitation, fluxes)

        daily_relative = np.max(np.abs(daily_residual)) / precipitation.max()
        assert daily_relative < tolerance

        budget = annual_budget(years, precipitation, etp, fluxes, weights)
        annual_relative = np.max(np.abs(budget.residual) / np.maximum(budget.precipitation, 1e-12))
        assert annual_relative < tolerance

        # The displayed/persisted closure (precipitation - ETR - recharge -
        # runoff - storage changes) must match the internal residual: the
        # lag's own delay line has to be counted too.
        displayed_storage_change = (
            budget.soil_storage_change
            + budget.transit_storage_change
            + budget.cn_storage_change
            + budget.lag_storage_change
        )
        displayed_residual = (
            budget.precipitation
            - budget.etr
            - budget.recharge
            - budget.runoff
            - displayed_storage_change
        )
        displayed_relative = np.max(
            np.abs(displayed_residual - budget.residual) / np.maximum(budget.precipitation, 1e-12)
        )
        assert displayed_relative < tolerance


def test_a_runoff_lag_moves_volume_from_early_years_to_later_ones_without_losing_any() -> None:
    """Over the whole run, the lag's delay line starts and nets out near zero.

    Nothing pushed past the last day (the lag is short next to the run), so
    the total curve-number runoff delivered matches the undelayed total.
    """
    precipitation, etp, ru_mm, years = _synthetic_forcing()
    weights = np.full(ru_mm.shape[0], 1.0 / ru_mm.shape[0])

    params_unlagged = SoilParameters(
        ru_mm=ru_mm,
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=80.0,
        runoff_time_days=1.0,
        runoff_lag_days=0.0,
    )
    params_lagged = SoilParameters(
        ru_mm=ru_mm,
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=80.0,
        runoff_time_days=1.0,
        runoff_lag_days=2.0,
    )

    unlagged = run_soil_balance(precipitation, etp, params_unlagged, full_soil(params_unlagged))
    lagged = run_soil_balance(precipitation, etp, params_lagged, full_soil(params_lagged))

    total_unlagged = float((unlagged.runoff_cn @ weights).sum())
    total_lagged = float((lagged.runoff_cn @ weights).sum())
    pushed_past_the_end = float(lagged.lag_storage[-1] @ weights)

    assert total_lagged + pushed_past_the_end == pytest.approx(total_unlagged, rel=1e-9)
