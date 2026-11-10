"""The count of cells a conditioned DEM cannot route."""

from __future__ import annotations

import numpy as np

from hydromodpy.catchment.terrain.undrained import undrained_cells


def _valid(elevation: np.ndarray) -> np.ndarray:
    return np.ones(elevation.shape, dtype=bool)


def test_a_flat_plateau_counts_every_interior_cell_without_descent() -> None:
    z = np.full((5, 5), 100.0)

    count = undrained_cells(z, _valid(z))

    assert count.without_descent == 9
    assert count.strict_pits == 0


def test_a_lone_pit_is_strict() -> None:
    z = np.full((3, 3), 100.0)
    z[1, 1] = 90.0

    count = undrained_cells(z, _valid(z))

    assert count.without_descent == 1
    assert count.strict_pits == 1


def test_an_edge_cell_never_counts() -> None:
    z = np.full((1, 3), 100.0)

    count = undrained_cells(z, _valid(z))

    assert count.without_descent == 0
    assert count.strict_pits == 0


def test_a_nodata_cell_never_counts_and_does_not_block_its_neighbours() -> None:
    z = np.full((3, 3), 100.0)
    valid = _valid(z)
    valid[1, 1] = False

    count = undrained_cells(z, valid)

    assert count.without_descent == 0
    assert count.strict_pits == 0


def test_an_equal_neighbour_keeps_the_cell_undrained_but_not_strict() -> None:
    z = np.full((5, 5), 10.0)
    z[1, 2] = 5.0
    z[2, 2] = 5.0

    count = undrained_cells(z, _valid(z))

    assert count.without_descent == 2
    assert count.strict_pits == 0
