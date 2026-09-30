"""A soil whose yearly demand outruns its yearly rain never settles: it says so.

``ru = 1000`` mm, 300 mm of rain and 900 mm of ETP spread evenly over the
year: the soil keeps draining every cycle instead of repeating, so
`spinup_state` runs out its `max_cycles` budget with `settled = False`.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import SoilParameters, spinup_state


def test_a_spinup_that_cannot_settle_says_so() -> None:
    n_days, n_columns = 365, 1
    precipitation = np.full((n_days, n_columns), 300.0 / n_days)
    etp = np.full((n_days, n_columns), 900.0 / n_days)
    params = SoilParameters(
        ru_mm=np.array([1000.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    spinup = spinup_state(precipitation, etp, params, max_cycles=3)

    assert spinup.settled is False
    assert spinup.cycles == 3
