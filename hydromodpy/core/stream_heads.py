"""The mapped network drawn from its heads, down the model's own descent.

A mapped path below a stream head is shaped by fields, ditches and rectified
reaches that a drain model on a DEM can never reproduce. Drawn cell by cell,
that shape is false error in the criterion: on the Flume Voronoi mesh the
crossing rule breaks the map into 1987 pieces, and 37 per cent of the mapped
cells drain into a cell the map does not touch. This rule keeps only where the
map says a stream starts, and lets the criterion graph draw the rest. The
drawn map is connected to the outlet by construction.

Which end of a free reach is its head is decided on the criterion graph, by
the drained area, never by the orientation of the line. Each end is read
through the largest drained area within the snap radius, not through its
nearest cell: the line runs beside the model talweg, and the cell nearest to a
confluence is often a hillside cell. On the Flume Voronoi mesh the nearest
cell kept 74 of 118 free ends, the window 112.

The candidates are found by the spatial layer (it owns shapely and the CRS);
they are defined here so core can consume them and spatial can return them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.topographic_distance import DownslopeMetric

__all__ = (
    "HeadCandidates",
    "HeadTrace",
    "HeadsSettings",
    "concat_candidates",
    "trace_from_heads",
)


def _points(values: np.ndarray, name: str) -> np.ndarray:
    """Return ``values`` as a float ``(n, 2)`` array, refusing another shape."""
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return np.empty((0, 2), dtype=float)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(f"{name} must have shape (n, 2), got {array.shape}.")
    return array


@dataclass(frozen=True, slots=True)
class HeadCandidates:
    """The free ends of a mapped network, in the mesh CRS.

    ``head_xy`` holds each free end, ``reach_end_xy`` the other end of the
    merged reach it closes, row for row. ``map_points_xy`` samples the lines
    at a fixed step, for the agreement between the trace and the map.
    """

    head_xy: np.ndarray
    reach_end_xy: np.ndarray
    map_points_xy: np.ndarray

    def __post_init__(self) -> None:
        heads = _points(self.head_xy, "head_xy")
        ends = _points(self.reach_end_xy, "reach_end_xy")
        if heads.shape != ends.shape:
            raise ValueError(
                f"head_xy and reach_end_xy pair row for row, got {heads.shape} and {ends.shape}."
            )
        object.__setattr__(self, "head_xy", heads)
        object.__setattr__(self, "reach_end_xy", ends)
        object.__setattr__(self, "map_points_xy", _points(self.map_points_xy, "map_points_xy"))

    @property
    def n_candidates(self) -> int:
        """How many free ends the map holds."""
        return int(self.head_xy.shape[0])


def concat_candidates(a: HeadCandidates, b: HeadCandidates) -> HeadCandidates:
    """Return the candidates of two maps together.

    The maximal map is traced from the heads of both maps, so it contains the
    trace of the minimal one. Each end keeps the reach end of its own map.
    """
    return HeadCandidates(
        head_xy=np.concatenate([a.head_xy, b.head_xy]),
        reach_end_xy=np.concatenate([a.reach_end_xy, b.reach_end_xy]),
        map_points_xy=np.concatenate([a.map_points_xy, b.map_points_xy]),
    )


@dataclass(frozen=True, slots=True)
class HeadsSettings:
    """Where a head may land: within a radius, on a cell draining enough."""

    snap_radius_m: float
    min_drained_area_m2: float


@dataclass(frozen=True, slots=True)
class HeadTrace:
    """The map drawn from its heads, and how each head landed."""

    traced: np.ndarray
    """(n_cells,) bool: the drawn map."""

    head_xy: np.ndarray
    """(k, 2): the candidates kept as heads."""

    head_cell: np.ndarray
    """(k,) int: the cell each head landed on, -1 when lost."""

    snap_distance_m: np.ndarray
    """(k,) float: head to landing cell centre, NaN when lost."""

    n_candidates: int
    """Free ends examined."""

    near_map_share: float
    """Share of traced cells within ``snap_radius_m`` of the map, NaN if none."""

    settings: HeadsSettings

    @property
    def n_lost(self) -> int:
        """Heads with no landing cell within the radius."""
        return int(np.count_nonzero(self.head_cell < 0))

    @property
    def indices(self) -> dict[str, float]:
        """The numbers a trial publishes about the heads."""
        landed = self.snap_distance_m[np.isfinite(self.snap_distance_m)]
        return {
            "n_heads": float(self.head_cell.size),
            "n_heads_lost": float(self.n_lost),
            "head_snap_p90_m": float(np.percentile(landed, 90.0)) if landed.size else float("nan"),
            "heads_trace_near_map_share": float(self.near_map_share),
        }


def _window_area(tree, drained: np.ndarray, points: np.ndarray, radius: float) -> np.ndarray:
    """Return the largest drained area within ``radius`` of each point.

    A point with no cell centre within the radius, on a mesh coarser than it,
    reads its nearest cell.
    """
    nearest = tree.query(points)[1]
    area = drained[nearest].astype(float)
    for row, cells in enumerate(tree.query_ball_point(points, r=radius)):
        if cells:
            area[row] = float(drained[cells].max())
    return area


def trace_from_heads(
    metric: DownslopeMetric,
    candidates: HeadCandidates,
    *,
    cell_area_m2: np.ndarray,
    settings: HeadsSettings,
) -> HeadTrace:
    """Draw the map from its heads down ``metric.graph``.

    A free end is kept as a head when the largest drained area within
    ``settings.snap_radius_m`` of it does not exceed the same window at its
    reach end (:func:`_window_area`). A tie keeps it: a short reach reads one
    talweg at both ends, and a head kept twice traces one path.
    Each head lands on the nearest active cell draining at least
    ``settings.min_drained_area_m2`` within ``settings.snap_radius_m``, else it
    is lost. The trace follows the receivers from every landing cell until the
    descent ends or meets a traced cell. It does not stop at the outlet: like
    the crossing rule, the map may continue into the buffer, and the supports
    are cut to the catchment downstream.
    """
    from scipy.spatial import cKDTree

    graph = metric.graph
    areas = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    accumulated = accumulate_on_downhill_graph(graph, np.where(np.isfinite(areas), areas, 0.0))
    usable = np.flatnonzero(graph.active & np.isfinite(accumulated))
    radius = float(settings.snap_radius_m)
    threshold = float(settings.min_drained_area_m2)
    n_candidates = candidates.n_candidates

    def refuse(reason: str) -> ValueError:
        return ValueError(
            f"the mapped network draws no stream from its heads: {reason} "
            f"({n_candidates} free end(s) examined, snap radius {radius:g} m, minimum "
            f"drained area {threshold / 1.0e6:g} km2). Widen the radius, lower the "
            "drained area, or draw the map by 'crossing'."
        )

    if n_candidates == 0 or usable.size == 0:
        raise refuse("the map holds no free end on an active cell")
    centres = np.asarray(metric.centroids, dtype=float)[:, :2]
    tree = cKDTree(centres[usable])
    drained = accumulated[usable]
    head_area = _window_area(tree, drained, candidates.head_xy, radius)
    end_area = _window_area(tree, drained, candidates.reach_end_xy, radius)
    head_xy = candidates.head_xy[head_area <= end_area]
    if head_xy.shape[0] == 0:
        raise refuse("every free end drains more than the other end of its reach")

    landing = usable[accumulated[usable] >= threshold]
    head_cell = np.full(head_xy.shape[0], -1, dtype=np.int64)
    snap_distance = np.full(head_xy.shape[0], np.nan, dtype=float)
    if landing.size:
        distance, slot = cKDTree(centres[landing]).query(head_xy, distance_upper_bound=radius)
        landed = np.isfinite(distance)
        head_cell[landed] = landing[slot[landed]]
        snap_distance[landed] = distance[landed]
    if not np.any(head_cell >= 0):
        raise refuse(f"every one of the {head_xy.shape[0]} head(s) is lost")

    traced = np.zeros(graph.active.size, dtype=bool)
    downstream = graph.downstream
    for start in head_cell[head_cell >= 0].tolist():
        cell = int(start)
        while cell >= 0 and not traced[cell]:
            traced[cell] = True
            cell = int(downstream[cell])

    near_share = float("nan")
    if candidates.map_points_xy.shape[0]:
        gap, _ = cKDTree(candidates.map_points_xy).query(
            centres[traced], distance_upper_bound=radius
        )
        near_share = float(np.mean(np.isfinite(gap)))

    return HeadTrace(
        traced=traced,
        head_xy=head_xy,
        head_cell=head_cell,
        snap_distance_m=snap_distance,
        n_candidates=n_candidates,
        near_map_share=near_share,
        settings=settings,
    )
