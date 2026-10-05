"""A cell a hair above the flood level is raised and gets a receiver.

The floor next to the spill is flooded to ``spill + epsilon``; the next cell
lies ``2e-10`` m above that, below the drop the receiver graph tells from a
flat. Left as it stands it would have no lower neighbour; the flood raises it
like a cell below the level.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.depression_filling import DEFAULT_EPSILON_M
from tests.unit.core._descent_meshes import grid_descent

SPILL = 0.0
HAIR = SPILL + DEFAULT_EPSILON_M + 2.0e-10
N_COLS = 5
FLOOR, PROBE = N_COLS + 1, N_COLS + 2


def _strip() -> np.ndarray:
    top = np.full((3, N_COLS), 10.0)
    top[1, :] = [SPILL, SPILL, HAIR, 5.0, 10.0]
    return top


def test_the_probe_is_raised_and_drains_to_the_floor() -> None:
    descent = grid_descent(_strip())

    assert descent.surface[FLOOR] == SPILL + DEFAULT_EPSILON_M
    assert descent.surface[PROBE] > HAIR
    assert int(descent.receiver[PROBE]) == FLOOR
    assert descent.n_raised == 2
