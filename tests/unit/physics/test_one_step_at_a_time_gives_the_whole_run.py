"""Calling `soil_step` one day at a time reproduces `run_soil_balance` exactly.

`run_soil_balance` is documented to only call `soil_step` in a loop: this
pins that contract so the two never drift apart.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
    soil_step,
)


def test_one_step_at_a_time_gives_the_whole_run() -> None:
    rng = np.random.default_rng(5)
    n_days, n_columns = 40, 6
    precipitation = rng.gamma(1.0, 4.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=rng.uniform(20.0, 200.0, n_columns),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.1,
        bypass_fraction=0.05,
        transit_time_days=4.0,
    )
    initial = full_soil(params)

    fluxes = run_soil_balance(precipitation, etp, params, initial)

    state = initial
    etr = np.empty((n_days, n_columns))
    residual_etp = np.empty((n_days, n_columns))
    recharge = np.empty((n_days, n_columns))
    runoff = np.empty((n_days, n_columns))
    for t in range(n_days):
        state, day = soil_step(state, precipitation[t], etp[t], params)
        etr[t] = day.etr
        residual_etp[t] = day.residual_etp
        recharge[t] = day.recharge
        runoff[t] = day.runoff

    assert np.array_equal(fluxes.etr, etr)
    assert np.array_equal(fluxes.residual_etp, residual_etp)
    assert np.array_equal(fluxes.recharge, recharge)
    assert np.array_equal(fluxes.runoff, runoff)
    assert np.array_equal(fluxes.end.soil_mm, state.soil_mm)
    assert np.array_equal(fluxes.end.transit_mm, state.transit_mm)
