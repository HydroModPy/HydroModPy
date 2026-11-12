"""The count of cells a conditioned DEM cannot route."""

from __future__ import annotations

import numpy as np

from hydromodpy.catchment.terrain.undrained import undrained_cells


def _valid(elevation: np.ndarray) -> np.ndarray:
    return np.ones(elevation.shape, dtype=bool)


def test_a_nodata_cell_never_counts_and_does_not_block_its_neighbours() -> None:
    z = np.full((3, 3), 100.0)
    valid = _valid(z)
    valid[1, 1] = False

    count = undrained_cells(z, valid)

    assert count.without_descent == 0
    assert count.strict_pits == 0
