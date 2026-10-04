"""A free end whose window ties with its reach end is kept as a head.

A short reach near the outlet reads the same talweg cell from both ends.
Keeping the end costs nothing: a head kept twice traces one path, while a
head dropped on a tie loses the reach.
"""

from __future__ import annotations

import numpy as np

from tests.unit.core._heads_valley import AXIS, N_ROWS, candidates, cell, centre, valley_geometry


def test_a_tie_between_both_ends_keeps_the_head() -> None:
    head, reach_end = centre(N_ROWS - 3, AXIS + 2), centre(N_ROWS - 2, AXIS + 1)

    geometry = valley_geometry(candidates([(head, reach_end)]), snap_radius_m=50.0)

    assert geometry.heads is not None
    np.testing.assert_allclose(geometry.heads.head_xy, [head])
    assert geometry.observed[cell(N_ROWS - 1, AXIS)]
