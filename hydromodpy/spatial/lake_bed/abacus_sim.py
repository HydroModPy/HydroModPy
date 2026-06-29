"""Compute the simulated abacus by flooding a per-cell lake bed.

Given the carved (or raw) bed elevation and plan area of each lake cell, the
stage-volume-area relation the model actually represents is, at stage ``z``:

* wetted area  ``A(z) = sum(area_c for bed_c < z)``
* storage      ``V(z) = sum(area_c * max(0, z - bed_c))``

Comparing this simulated abacus to the user abacus is the diagnostic that tells
whether the carved bed reproduces the real filling.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

__all__ = ["simulate_abacus"]


def simulate_abacus(
    *,
    bed_by_cell: Mapping[int, float],
    area_by_cell: Mapping[int, float],
    stages: Sequence[float],
) -> dict[str, np.ndarray]:
    """Return ``{'stage', 'volume', 'sarea'}`` arrays from a per-cell bed.

    ``stages`` are the elevations at which to evaluate the flooded volume and
    wetted area (typically the abacus stage column, so the curves are directly
    comparable).
    """
    cells = sorted(int(c) for c in bed_by_cell)
    if not cells:
        raise ValueError("simulate_abacus: no lake cells")
    bed = np.array([float(bed_by_cell[c]) for c in cells], dtype=float)
    area = np.array([float(area_by_cell[c]) for c in cells], dtype=float)
    stage = np.asarray(stages, dtype=float)

    depth = stage[:, None] - bed[None, :]  # (n_stages, n_cells)
    wet = depth > 0.0
    volume = np.sum(np.where(wet, depth, 0.0) * area[None, :], axis=1)
    sarea = np.sum(np.where(wet, area[None, :], 0.0), axis=1)
    return {"stage": stage, "volume": volume, "sarea": sarea}
