"""The free ends of a mapped stream network, where its heads may lie.

The heads rule of the network criterion keeps only where the map says a
stream starts (:mod:`hydromodpy.core.stream_heads`). A head is found
geometrically, for every source alike: no provider reads node codes, and the
direction a line was digitised in is never trusted. This module only finds the
free ends and the other end of each merged reach; which end is upstream is
decided on the criterion graph, by the drained area.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.stream_heads import HeadCandidates
from hydromodpy.spatial.mesh.ops.vector_cell_mask import _line_parts, _to_mesh_crs

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from hydromodpy.spatial.mesh.ops.vector_cell_mask import CrsLike

__all__ = ["network_head_candidates"]

_END_DECIMALS = 2
"""Endpoints are matched on coordinates rounded to 0.01 m.

The noding computes junction points in floating point; two lines meeting at
one junction can carry it a few ulps apart. A centimetre is far below what a
map resolves and far above that noise.
"""


def network_head_candidates(
    lines: Sequence[BaseGeometry],
    *,
    mesh_crs: CrsLike,
    geometry_crs: CrsLike,
    sample_step_m: float = 10.0,
) -> HeadCandidates:
    """Return the free ends of ``lines`` and the other end of each one's reach.

    The lines are reprojected to the mesh CRS, noded at every intersection by
    ``shapely.union_all`` (a T junction without a shared vertex included),
    and merged between junctions and free ends by ``shapely.line_merge``. A
    free end is an endpoint met once; a closed ring has none, and the point
    where a reach meets it is a junction. ``map_points_xy`` samples every line
    each ``sample_step_m``, ends included.
    """
    import shapely

    if not sample_step_m > 0.0:
        raise ValueError(f"sample_step_m must be positive, got {sample_step_m!r}.")
    parts = _line_parts(_to_mesh_crs(list(lines), mesh_crs=mesh_crs, geometry_crs=geometry_crs))
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

    samples: list[np.ndarray] = []
    for line in merged:
        steps = np.append(np.arange(0.0, line.length, float(sample_step_m)), line.length)
        samples.append(shapely.get_coordinates(shapely.line_interpolate_point(line, steps)))

    return HeadCandidates(
        head_xy=np.asarray(head_xy, dtype=float).reshape(-1, 2),
        reach_end_xy=np.asarray(reach_end_xy, dtype=float).reshape(-1, 2),
        map_points_xy=np.concatenate(samples).reshape(-1, 2),
    )
