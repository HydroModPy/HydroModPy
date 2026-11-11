"""Count the cells a conditioned DEM leaves without a descent.

A D8 pointer needs a strictly lower neighbour to drain. The count is read on
the conditioned DEM of one terrain product, once, and kept in its
``terrain.json``. A cell on the raster edge or beside a nodata cell drains out,
so it is never counted.

A ``fill`` leaves 0 strict pits and 0 cells without descent. A Whitebox ``breach``
leaves 13 strict pits and 18 cells without descent on the Nançon 25 m, and 30 and 873 on
the massif 75 m. A QGIS fill without a minimal slope leaves 0 strict pits and 14 274
flat cells on the Nançon.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class UndrainedCells:
    """The cells a DEM cannot route, and the strict pits among them.

    ``without_descent`` counts every valid cell with no strictly lower
    neighbour. ``strict_pits`` counts the subset whose eight neighbours are all
    strictly higher.
    """

    without_descent: int
    strict_pits: int


def undrained_cells(elevation: np.ndarray, valid: np.ndarray) -> UndrainedCells:
    """Count the cells of *elevation* with no strictly lower neighbour.

    *valid* marks the cells that hold an elevation, so a nodata cell never
    counts and never blocks the descent of its neighbours. A cell on the edge
    of the array counts as draining out.
    """
    z = np.asarray(elevation, dtype=float)
    mask = np.asarray(valid, dtype=bool)
    zz = np.where(mask, z, -np.inf)
    padded = np.pad(zz, 1, constant_values=-np.inf)
    height, width = z.shape
    lowest = np.full(z.shape, np.inf)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            neighbour = padded[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
            lowest = np.minimum(lowest, neighbour)
    strict = mask & (lowest > z)
    without_descent = mask & (lowest >= z)
    return UndrainedCells(
        without_descent=int(without_descent.sum()),
        strict_pits=int(strict.sum()),
    )


__all__ = ["UndrainedCells", "undrained_cells"]
