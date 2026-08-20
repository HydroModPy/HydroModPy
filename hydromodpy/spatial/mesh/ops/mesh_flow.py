"""Solver-agnostic single-flow-direction hydrography on an unstructured mesh.

Steepest-descent receiver, flow accumulation and pit spill on a planar cell mesh,
expressed only from the per-cell top elevation, the face adjacency (see
``cell_adjacency``) and the cell centroids. It has no solver or package dependency, so
the same primitives serve every backend (MODFLOW 6 DISV, MODFLOW-NWT DIS, Boussinesq
triangles) and the diagnostic tools, instead of each re-deriving steepest descent.

The raster catchment/stream delineation (flow accumulation on the DEM) lives in
``spatial/geographic``; this is its mesh-native counterpart, used once the DEM has been
projected onto the solver grid.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


def steepest_descent_receiver(
    top: np.ndarray,
    cell_adjacency: Sequence[set[int]],
    cell_centroids: np.ndarray,
    active: np.ndarray | None = None,
) -> np.ndarray:
    """Single-flow-direction receiver: the steepest active face-neighbour, -1 at a sink."""
    n = int(np.asarray(top).shape[0])
    receiver = np.full(n, -1, dtype=int)
    for cell in range(n):
        if active is not None and not active[cell]:
            continue
        z = top[cell]
        cx, cy = float(cell_centroids[cell][0]), float(cell_centroids[cell][1])
        best, best_slope = -1, 0.0
        for nb in cell_adjacency[cell]:
            if active is not None and not active[nb]:
                continue
            dz = z - top[nb]
            if dz <= 0.0:
                continue
            dist = math.hypot(cx - float(cell_centroids[nb][0]), cy - float(cell_centroids[nb][1]))
            slope = dz / dist if dist > 0.0 else dz
            if slope > best_slope:
                best_slope, best = slope, int(nb)
        receiver[cell] = best
    return receiver


def flow_accumulation(receiver: np.ndarray) -> np.ndarray:
    """Upstream cell count (self included) by draining each cell down its receiver."""
    n = receiver.shape[0]
    acc = np.ones(n, dtype=np.int64)
    order = np.argsort(-np.asarray([_chain_length(i, receiver) for i in range(n)]))
    for cell in order:
        r = int(receiver[cell])
        if r >= 0:
            acc[r] += acc[cell]
    return acc


def _chain_length(cell: int, receiver: np.ndarray) -> int:
    """Steps from a cell to its terminal (bounded walk; cycles guarded)."""
    steps, seen = 0, set()
    while receiver[cell] >= 0 and cell not in seen:
        seen.add(cell)
        cell = int(receiver[cell])
        steps += 1
        if steps > receiver.shape[0]:
            break
    return steps


def lowest_unvisited_neighbour(
    cell: int,
    cell_adjacency: Sequence[set[int]],
    top: np.ndarray,
    active: np.ndarray,
    visited: set[int],
) -> int | None:
    """The lowest active neighbour not yet on this walk, else ``None``.

    Used to spill over a residual pit or a flat: stepping to the lowest unvisited rim
    carries a trace over the obstacle. The per-walk ``visited`` set makes the walk
    strictly advancing, so it cannot loop.
    """
    best, best_top = None, None
    for nb in cell_adjacency[cell]:
        if not active[nb] or nb in visited:
            continue
        tnb = float(top[nb])
        if best_top is None or tnb < best_top:
            best, best_top = int(nb), tnb
    return best


__all__ = ["steepest_descent_receiver", "flow_accumulation", "lowest_unvisited_neighbour"]
