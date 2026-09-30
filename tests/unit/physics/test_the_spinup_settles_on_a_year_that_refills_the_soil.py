"""A year whose winter rain always resaturates the soil settles in a few cycles.

Heavy winter rain far above every column's capacity, and a dry summer that
only draws the soil down, brings the end-of-year state back to the same
saturated soil every cycle: `spinup_state` should settle quickly.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import SoilParameters, spinup_state
from tests._helpers.tolerances import tol


def test_the_spinup_settles_on_a_year_that_refills_the_soil() -> None:
    n_days, n_columns = 365, 5
    day = np.arange(n_days)
    is_winter = (day < 90) | (day >= 270)
    precipitation = np.where(is_winter, 5.0, 0.0)[:, np.newaxis]
    precipitation = np.broadcast_to(precipitation, (n_days, n_columns)).copy()
    etp = np.where(is_winter, 0.0, 3.0)[:, np.newaxis]
    etp = np.broadcast_to(etp, (n_days, n_columns)).copy()
    params = SoilParameters(
        ru_mm=np.array([50.0, 100.0, 150.0, 200.0, 250.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    spinup = spinup_state(precipitation, etp, params)

    assert spinup.settled is True
    assert spinup.cycles <= 3
    assert spinup.last_change_mm < tol("soil_spin_up_settling")
