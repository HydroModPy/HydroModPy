"""A soil of zero capacity holds no water: it evaporates then passes the rest through.

Section 7 fixes the evaporation ratio to 1 at the ``ru = 0`` limit (the
prototype's choice), so the soil never stores anything and what the ETR
leaves goes straight to the recharge.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)


def test_a_soil_with_no_capacity_passes_the_rain_through() -> None:
    rng = np.random.default_rng(1)
    n_days, n_columns = 50, 4
    precipitation = rng.gamma(1.0, 5.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 4.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=np.zeros(n_columns),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.all(fluxes.soil_storage == 0.0)
    assert np.max(np.abs(fluxes.recharge - (precipitation - fluxes.etr))) < 1e-12
