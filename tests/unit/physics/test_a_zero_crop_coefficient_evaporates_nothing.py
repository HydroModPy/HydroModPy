"""A crop coefficient of zero shuts the ETR off entirely.

``kc = 0`` makes the demand ``D = kc * ETP`` zero regardless of ETP, alpha or
ru, so nothing evaporates and the ETP the soil left unmet equals the ETP that
was loaded.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)


def test_a_zero_crop_coefficient_evaporates_nothing() -> None:
    rng = np.random.default_rng(2)
    n_days, n_columns = 30, 5
    precipitation = rng.gamma(1.0, 5.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 4.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=rng.uniform(10.0, 200.0, n_columns),
        alpha=0.6,
        kc=0.0,
        impervious_fraction=0.1,
        bypass_fraction=0.05,
        transit_time_days=3.0,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.all(fluxes.etr == 0.0)
    assert np.all(fluxes.residual_etp == 0.0)
