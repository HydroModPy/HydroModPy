"""Move a gauge onto the most accumulated cell within a radius, on request.

A gauge coordinate is rarely on the talweg the model routes on. Measured on the
Nancon at the basin outlet, the gauge's own coordinate resolves to a cell
draining 0.107 km2 of a 64.6 km2 catchment. That is why a discharge station is
not located by its coordinate by default, and why this snap is opt-in: turning
it on for everyone would move every single-outlet project.

The rule is the one the outlet snap of the delineation applies: the highest
accumulation wins, ties go to the nearest cell, then to the lowest index. The
support differs on purpose. The delineation snaps on the DEM raster, and its
snapped outlet was measured to resolve to a mesh cell draining 0.022 km2 of the
same catchment. A gauge is scored on the mesh, so it is snapped on the area the
solver itself accumulates on the mesh, with the routing graph its discharge is
read on. The search region is a disc of ``radius_m`` around the gauge, so the
radius is a maximum displacement, not the window width ``snap_dist`` is.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class GaugeSnapError(ValueError):
    """The snap radius reaches no cell but the one the gauge already sits in."""


@dataclass(frozen=True)
class GaugeSnap:
    """Where a gauge was, where it went, and what each cell drains."""

    index_before: int
    index_after: int
    distance_m: float
    """Distance from the gauge coordinate to the centre of the chosen cell."""

    area_before_m2: float
    area_after_m2: float

    @property
    def moved(self) -> bool:
        return self.index_after != self.index_before


def snap_to_most_accumulated(
    centroids: np.ndarray,
    accumulation: np.ndarray,
    *,
    x: float,
    y: float,
    radius_m: float,
    start_index: int,
) -> GaugeSnap:
    """Return the most accumulated cell whose centre lies within ``radius_m``.

    ``centroids`` is ``(n_cells, 2+)`` and ``accumulation`` ``(n_cells,)``, in
    the flat order of the mesh. ``start_index`` is the cell the gauge resolved
    to before the snap; it stays a candidate, so a gauge already on the talweg
    does not move. A radius that reaches no other cell is refused, with the
    distance to the nearest one: the user asked for a snap and none can happen.
    """
    if not radius_m > 0.0:
        raise GaugeSnapError(f"a snap radius must be > 0 m, got {radius_m}.")
    xy = np.asarray(centroids, dtype=float)[:, :2]
    acc = np.asarray(accumulation, dtype=float).reshape(-1)
    if xy.shape[0] != acc.size:
        raise ValueError(
            f"the mesh holds {xy.shape[0]} cell centres and the accumulation {acc.size} values."
        )
    if not 0 <= start_index < acc.size:
        raise ValueError(f"start cell {start_index} is outside the {acc.size} cells.")

    distance = np.hypot(xy[:, 0] - float(x), xy[:, 1] - float(y))
    # A cell outside the delineated catchment accumulates nothing, and NaN is a
    # cell the graph never reached: neither is a place a gauge can stand.
    usable = np.isfinite(acc) & (acc > 0.0)
    reachable = usable & (distance <= float(radius_m))
    others = reachable.copy()
    others[start_index] = False
    if not others.any():
        candidates = np.flatnonzero(usable)
        candidates = candidates[candidates != start_index]
        nearest = float(distance[candidates].min()) if candidates.size else float("nan")
        raise GaugeSnapError(
            f"a snap radius of {radius_m:g} m around ({x:.2f}, {y:.2f}) reaches no cell but "
            f"the one the gauge already sits in; the nearest other cell of the catchment is "
            f"{nearest:.1f} m away. Raise the radius past it, or drop it to score the "
            "gauge where it resolves."
        )

    reachable[start_index] = bool(usable[start_index])
    indices = np.flatnonzero(reachable)
    # Highest accumulation, then nearest, then lowest index: the outlet snap's
    # own order, so two identical requests snap identically.
    order = np.lexsort((indices, distance[indices], -acc[indices]))
    best = int(indices[order[0]])
    return GaugeSnap(
        index_before=int(start_index),
        index_after=best,
        distance_m=float(distance[best]),
        area_before_m2=float(acc[start_index]) if np.isfinite(acc[start_index]) else 0.0,
        area_after_m2=float(acc[best]),
    )


__all__ = ["GaugeSnap", "GaugeSnapError", "snap_to_most_accumulated"]
