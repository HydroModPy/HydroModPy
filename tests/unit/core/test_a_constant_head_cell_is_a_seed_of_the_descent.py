"""A constant-head cell passed as a base level is a seed of D.

Water leaves the model there, as it does on the domain rim. The bowl around
such a cell drains to it as it stands; without the seed the fill would raise
the whole bowl up to its rim.
"""

from __future__ import annotations

import numpy as np

from tests.unit.core._descent_meshes import grid_descent

N = 9
CENTRE = (N // 2) * N + N // 2


def _bowl() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    return 5.0 + (rows - N // 2) ** 2 + (cols - N // 2) ** 2


def _constant_head_at_the_centre() -> np.ndarray:
    base_level = np.zeros(N * N, dtype=bool)
    base_level[CENTRE] = True
    return base_level


def test_the_bowl_drains_to_the_constant_head_cell() -> None:
    descent = grid_descent(_bowl(), base_level=_constant_head_at_the_centre())

    assert descent.n_raised == 0
    assert descent.base_level[CENTRE]
    assert int(descent.receiver[CENTRE]) == -1
    assert np.all(descent.basin(CENTRE))


def test_without_the_seed_the_bowl_is_raised() -> None:
    descent = grid_descent(_bowl())

    assert descent.n_raised > 0
    assert not descent.base_level[CENTRE]
