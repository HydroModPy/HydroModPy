"""The sealed share of a column runs off at once; the soil only sees the rest.

``impervious_fraction`` weights every soil output by area: with ``f = 0.25``
the runoff is exactly ``0.25 * P``, the ETR never exceeds ``0.75 * kc * ETP``,
and what the soil could not evaporate on its unsealed share is the residual
ETP.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)


def test_the_sealed_share_neither_infiltrates_nor_evaporates() -> None:
    rng = np.random.default_rng(4)
    n_days, n_columns = 40, 5
    precipitation = rng.gamma(1.0, 5.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 4.0, (n_days, n_columns))
    kc = 1.2
    params = SoilParameters(
        ru_mm=rng.uniform(10.0, 200.0, n_columns),
        alpha=0.6,
        kc=kc,
        impervious_fraction=0.25,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.max(np.abs(fluxes.runoff - 0.25 * precipitation)) < 1e-12
    assert np.all(fluxes.etr <= 0.75 * kc * etp + 1e-12)
    assert np.max(np.abs(fluxes.residual_etp - 0.75 * (kc * etp - fluxes.etr / 0.75))) < 1e-12
