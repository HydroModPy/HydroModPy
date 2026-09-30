"""The by-pass reaches the recharge the same day, whether the soil is dry or not.

With ``S = 0``, ``RU = 150``, ``b = 0.2`` and ``P = 10``: the by-passed share
``0.2 * 10 = 2`` mm never enters the soil bucket, so it recharges on day 0
even though the dry soil absorbs the rest.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.hydrology.soil_reservoir.kernel import SoilParameters, SoilState, soil_step


def test_the_bypass_reaches_the_recharge_on_a_dry_soil() -> None:
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))
    params = SoilParameters(
        ru_mm=np.array([150.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.2,
        transit_time_days=0.0,
    )

    _, day = soil_step(state, np.array([10.0]), np.array([0.0]), params)

    assert day.recharge[0] == pytest.approx(2.0, abs=1e-12)
