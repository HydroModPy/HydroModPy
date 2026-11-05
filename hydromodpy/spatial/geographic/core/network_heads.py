"""The free ends of a mapped stream network, where its heads may lie.

The heads rule of the network criterion keeps only where the map says a
stream starts (:mod:`hydromodpy.results.derive.stream.heads`). A head is found
geometrically, for every source alike: no provider reads node codes, and the
direction a line was digitized in is never trusted. This module only finds the
free ends and the other end of each merged reach; which end is upstream is
decided on the criterion graph, by the drained area.

``line_parts`` splits a mapped network into its lines. The crossing rule of
:mod:`hydromodpy.spatial.mesh.cells.crossed_by_lines` reads it too, and a map with
anything but lines is refused by both.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from hydromodpy.core.io.crs import CrsLike

__all__ = ["HeadCandidates", "line_parts", "network_head_candidates"]

logger = get_logger(__name__)

_END_DECIMALS = 2
"""Endpoints are matched on coordinates rounded to 0.01 m.

The noding computes junction points in floating point; two lines meeting at
one junction can carry it a few ulps apart. A centimeter is far below what a
map resolves and far above that noise.
"""

_CUT_END_TOLERANCE_M = 0.01
"""A free end this close to the outline the map was cut along is an end of the cut.

The cut computes it on the outline in floating point, a few ulps off. The same
centimeter as :data:`_END_DECIMALS`, for the same reason. It is a length in meters, turned into
the units of the CRS of the cut before it is compared there.
"""

_METRE_IN_DEGREES = 1.0 / 111_320.0
"""A meter of a geographic CRS, in degrees: about, for a test on the order of a centimeter."""

_OUTLET_RADIUS_M = 100.0
"""A cut end this close to the outlet is where the catchment drains out, and is expected."""


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
    ``forced_cells`` are mesh cells that are heads whatever the map says, the
    foot of each dam: they come from the model, not from the lines, and carry
    no snap. ``n_cut_ends`` counts the free ends left out because the cut of the
    map to the catchment made them: the stream goes on beyond them.
    """

    head_xy: np.ndarray
    reach_end_xy: np.ndarray
    map_points_xy: np.ndarray
    forced_cells: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    n_cut_ends: int = 0

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
        forced = np.asarray(self.forced_cells, dtype=np.int64)
        if forced.ndim != 1:
            raise ValueError(f"forced_cells must be 1-D, got shape {forced.shape}.")
        object.__setattr__(self, "forced_cells", np.unique(forced))

    @property
    def n_candidates(self) -> int:
        """How many free ends the map holds."""
        return int(self.head_xy.shape[0])


def network_head_candidates(
    lines: Sequence[BaseGeometry],
    *,
    mesh_crs: CrsLike,
    geometry_crs: CrsLike,
    sample_step_m: float = 10.0,
    cut_outline: BaseGeometry | None = None,
    cut_crs: CrsLike | None = None,
    outlet_xy: tuple[float, float] | None = None,
) -> HeadCandidates:
    """Return the free ends of ``lines`` and the other end of each one's reach.

    The lines are reprojected to the mesh CRS, noded at every intersection by
    ``shapely.union_all`` (a T junction without a shared vertex included),
    and merged between junctions and free ends by ``shapely.line_merge``. A
    free end is an endpoint met once; a closed ring has none, and the point
    where a reach meets it is a junction. ``map_points_xy`` samples every line
    each ``sample_step_m``, ends included.

    ``cut_outline`` is the polygon, in ``cut_crs``, the lines were cut along. A
    free end on it was made by the cut: the stream goes on beyond it, so it is
    no head. It is left out and counted in ``n_cut_ends``. The other end of its
    reach stays, because which end drains more is still read through it.

    The ends are tested against the outline in the CRS of the cut, before any
    reprojection, where the outline is exact. A cut end other than the outlet
    (``outlet_xy``, in the mesh CRS) whose reach has no other free end is a reach
    nothing traces: it is warned about, and never becomes a head.
    """
    import shapely

    from hydromodpy.core.io.crs import to_mesh_crs

    if not sample_step_m > 0.0:
        raise ValueError(f"sample_step_m must be positive, got {sample_step_m!r}.")
    parts = line_parts(to_mesh_crs(list(lines), mesh_crs=mesh_crs, geometry_crs=geometry_crs))
    if not parts:
        empty = np.empty((0, 2), dtype=float)
        return HeadCandidates(head_xy=empty, reach_end_xy=empty, map_points_xy=empty)

    noded = shapely.union_all(np.asarray(parts, dtype=object))
    merged = [
        part
        for part in shapely.get_parts(shapely.line_merge(noded))
        if part.geom_type == "LineString" and part.length > 0.0
    ]

    # A closed ring (a pond outline, a self-touching line) has no free end, but
    # its closing point still counts twice: a reach meeting the ring there
    # ends at a junction, not at a source.
    ends: list[tuple[np.ndarray, np.ndarray]] = []
    ring_points: list[np.ndarray] = []
    for line in merged:
        coords = np.asarray(line.coords, dtype=float)[:, :2]
        if line.is_ring:
            ring_points.extend((coords[0], coords[-1]))
            continue
        ends.append((coords[0], coords[-1]))
    counts = Counter(
        tuple(np.round(point, _END_DECIMALS))
        for point in [*(point for pair in ends for point in pair), *ring_points]
    )
    head_xy: list[np.ndarray] = []
    reach_end_xy: list[np.ndarray] = []
    for first, last in ends:
        for point, other in ((first, last), (last, first)):
            if counts[tuple(np.round(point, _END_DECIMALS))] == 1:
                head_xy.append(point)
                reach_end_xy.append(other)
    heads = np.asarray(head_xy, dtype=float).reshape(-1, 2)
    reach_ends = np.asarray(reach_end_xy, dtype=float).reshape(-1, 2)
    n_cut_ends = 0
    if cut_outline is not None and heads.shape[0]:
        gap = _gap_to_the_outline(heads, cut_outline, mesh_crs=mesh_crs, cut_crs=cut_crs)
        kept = gap > _cut_end_tolerance(cut_crs)
        n_cut_ends = int(np.count_nonzero(~kept))
        _warn_of_reaches_nothing_traces(
            heads[~kept], reach_ends[~kept], heads[kept], outlet_xy=outlet_xy
        )
        heads, reach_ends = heads[kept], reach_ends[kept]

    samples: list[np.ndarray] = []
    for line in merged:
        steps = np.append(np.arange(0.0, line.length, float(sample_step_m)), line.length)
        samples.append(shapely.get_coordinates(shapely.line_interpolate_point(line, steps)))

    return HeadCandidates(
        head_xy=heads,
        reach_end_xy=reach_ends,
        map_points_xy=np.concatenate(samples).reshape(-1, 2),
        n_cut_ends=n_cut_ends,
    )


def _gap_to_the_outline(
    points: np.ndarray, outline: BaseGeometry, *, mesh_crs: CrsLike, cut_crs: CrsLike | None
) -> np.ndarray:
    """Return the distance of each mesh-CRS point to the outline, in the CRS of the cut."""
    import shapely
    from pyproj import Transformer

    from hydromodpy.core.io.crs import require_crs

    mesh = require_crs(mesh_crs, "mesh_crs")
    cut = require_crs(cut_crs, "cut_crs")
    if not mesh.equals(cut):
        x, y = Transformer.from_crs(mesh, cut, always_xy=True).transform(points[:, 0], points[:, 1])
        points = np.column_stack([x, y])
    return np.asarray(shapely.distance(shapely.points(points), outline.boundary), dtype=float)


def _cut_end_tolerance(cut_crs: CrsLike | None) -> float:
    """Return :data:`_CUT_END_TOLERANCE_M` in the units of the CRS of the cut."""
    from hydromodpy.core.io.crs import require_crs

    cut = require_crs(cut_crs, "cut_crs")
    if cut.is_geographic:
        return _CUT_END_TOLERANCE_M * _METRE_IN_DEGREES
    return _CUT_END_TOLERANCE_M / float(cut.axis_info[0].unit_conversion_factor)


def _warn_of_reaches_nothing_traces(
    cut: np.ndarray,
    other_ends: np.ndarray,
    kept: np.ndarray,
    *,
    outlet_xy: tuple[float, float] | None,
) -> None:
    """Warn of each cut end, but the outlet, whose reach has no free end left to trace it.

    Under the heads rule a reach is drawn from a free end. One whose only free end
    lies on the outline is drawn by nothing, so the mapped network lacks it. It is
    not made a head: the stream goes on beyond the outline.
    """
    if not cut.shape[0]:
        return
    kept_keys = {tuple(np.round(point, _END_DECIMALS)) for point in kept}
    lost = 0
    for point, other in zip(cut, other_ends, strict=True):
        if tuple(np.round(other, _END_DECIMALS)) in kept_keys:
            continue
        if outlet_xy is not None and np.hypot(*(point - np.asarray(outlet_xy))) <= _OUTLET_RADIUS_M:
            continue
        lost += 1
    if lost:
        logger.warning(
            "%d reach(es) of the mapped network have no free end inside the catchment (their "
            "only upstream end lies on the outline the map was cut along, away from the "
            "outlet). The heads rule draws nothing for them, so they are missing from the "
            "map the criterion scores against.",
            lost,
        )


def line_parts(geometries: Sequence[BaseGeometry]) -> list[BaseGeometry]:
    """Split multi-part and collection geometries into their lines of non-zero length.

    Anything but a line is refused, because the crossing rule rasterizes lines.
    """
    from hydromodpy.spatial.geographic.core.river_mesh_trace import linear_parts

    lines = linear_parts(geometries, refusal="the crossing rule rasterizes lines")
    return [line for line in lines if line.length > 0.0]
