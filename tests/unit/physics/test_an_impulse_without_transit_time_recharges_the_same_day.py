"""With no transit delay, a rain pulse above the soil capacity leaves the same day.

``transit_time_days = 0`` is the special case of section 7 where the linear
reservoir is skipped: what overflows the soil reaches the recharge without a
tail.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)


def test_an_impulse_without_transit_time_recharges_the_same_day() -> None:
    precipitation = np.array([[50.0], [0.0], [0.0], [0.0], [0.0]])
    etp = np.zeros_like(precipitation)
    params = SoilParameters(
        ru_mm=np.array([100.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.array_equal(fluxes.recharge[:, 0], [50.0, 0.0, 0.0, 0.0, 0.0])
