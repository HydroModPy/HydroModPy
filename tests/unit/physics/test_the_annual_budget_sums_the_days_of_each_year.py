"""The annual budget sums each calendar year's days, partial years included.

Two years back to back, the second cut short, check that `annual_budget`
sums exactly the days of each year and that `basin()` applies the declared
weights.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    annual_budget,
    full_soil,
    run_soil_balance,
)


def test_the_annual_budget_sums_the_days_of_each_year() -> None:
    rng = np.random.default_rng(6)
    n_columns = 4
    days_year_one, days_year_two = 365, 100
    n_days = days_year_one + days_year_two
    years = np.concatenate([np.full(days_year_one, 2015), np.full(days_year_two, 2016)])
    precipitation = rng.gamma(1.0, 4.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=rng.uniform(20.0, 200.0, n_columns),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=3.0,
    )
    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
    weights = np.full(n_columns, 1.0 / n_columns)

    budget = annual_budget(years, precipitation, etp, fluxes, weights)

    assert np.array_equal(budget.years, [2015, 2016])
    assert np.array_equal(budget.days, [365, 100])
    assert np.allclose(budget.precipitation[0], precipitation[:365].sum(axis=0), atol=1e-12)
    assert np.allclose(budget.precipitation[1], precipitation[365:].sum(axis=0), atol=1e-12)
    assert np.allclose(budget.etr[0], fluxes.etr[:365].sum(axis=0), atol=1e-12)
    assert np.allclose(budget.recharge[1], fluxes.recharge[365:].sum(axis=0), atol=1e-12)

    basin_recharge = budget.basin("recharge")
    assert np.allclose(basin_recharge, budget.recharge @ weights, atol=1e-12)
