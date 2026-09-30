"""With no rain at all, nothing runs off and nothing recharges: the soil only dries.

``impervious_fraction * 0 = 0`` and a soil that starts at or below ``ru``
never crosses it without rain, so the storage only falls as the ETR draws it
down.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)


def test_no_rain_recharges_nothing() -> None:
    rng = np.random.default_rng(3)
    n_days, n_columns = 60, 5
    precipitation = np.zeros((n_days, n_columns))
    etp = rng.uniform(0.0, 4.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=rng.uniform(10.0, 200.0, n_columns),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.2,
        bypass_fraction=0.1,
        transit_time_days=5.0,
    )
    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.all(fluxes.recharge == 0.0)
    assert np.all(fluxes.runoff == 0.0)
    storage = np.concatenate(
        [fluxes.soil_storage_start[np.newaxis, :], fluxes.soil_storage], axis=0
    )
    assert np.all(np.diff(storage, axis=0) <= 0.0)
