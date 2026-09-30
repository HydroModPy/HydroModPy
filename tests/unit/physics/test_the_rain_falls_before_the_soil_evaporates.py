"""The day's rain reaches the soil before the ETR is computed on it.

Order matters in section 7: with ``S = 0``, ``RU = 100``, ``alpha = 0.5``,
``P = 10`` and ``ETP = 4``, the wet soil is ``W = 10`` before ETR, so
``ETR = min(10, 4 * min(1, 10 / 50)) = 0.8``. Evaporating first, on the dry
soil, would give zero instead.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.hydrology.soil_reservoir.kernel import SoilParameters, SoilState, soil_step


def test_the_rain_falls_before_the_soil_evaporates() -> None:
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))
    params = SoilParameters(
        ru_mm=np.array([100.0]),
        alpha=0.5,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    _, day = soil_step(state, np.array([10.0]), np.array([4.0]), params)

    assert day.etr[0] == pytest.approx(0.8, abs=1e-15)
