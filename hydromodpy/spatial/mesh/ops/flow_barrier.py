"""Map a vector barrier line onto the faces of a cell mesh it crosses.

A flow barrier (MODFLOW 6 HFB) is a thin vertical low-permeability wall placed on
the SHARED FACE between two adjacent cells, so it needs no grid refinement and is
grid-independent (DIS / DISV / DISU). This module turns a polyline (a dam axis, a
cutoff-wall / grout-curtain trace) into the list of cell-pair faces it crosses,
each tagged with the line position so a per-segment depth can be interpolated.

Reference: the HFB6 package, Langevin et al. (2017), MODFLOW 6 TM 6-A55.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely.strtree import STRtree

if TYPE_CHECKING:
    from shapely.geometry import LineString

    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = ["BarrierFace", "barrier_faces_from_line"]


@dataclass(frozen=True)
class BarrierFace:
    """One mesh face crossed by a barrier line.

    ``cell_a`` / ``cell_b`` are the two adjacent cell2d ids sharing the face,
    ``cell_a < cell_b``; ``s`` is the normalized position [0, 1] of the crossing
    along the line, used to interpolate a per-vertex depth onto the face.
    """

    cell_a: int
    cell_b: int
    s: float


def barrier_faces_from_line(cell_mesh: PlanarCellMesh, line: LineString) -> list[BarrierFace]:
    """Return the interior mesh faces that make a CONTINUOUS cut along a barrier line.

    A face (interior edge shared by two cells) is barred when the trace passes
    BETWEEN the two cells, i.e. it crosses the segment joining their centres,
    the ``centers`` of the cell mesh (the Voronoi generators on a dual). This
    selects the full chain of cell-pair faces the line separates, so the
    barrier is a single connected fence with no leak paths -- unlike barring only
    the edges the trace clips, which leaves gaps where a cell the line passes
    through stays connected to both sides. The criterion is mesh-adaptive (no
    corridor width) and shape-agnostic (any polyline), and it never trips on a
    trace collinear with a mesh edge. ``s`` is the edge midpoint's normalized
    position along the line, for per-vertex depth interpolation. Faces are
    returned ordered along the line, ties in edge order.
    """
    geometry = cell_mesh.geometry
    interior = np.flatnonzero(geometry.edge_cells[:, 1] >= 0)
    pairs = geometry.edge_cells[interior]
    centers = cell_mesh.centers
    segments = shapely.linestrings(np.stack([centers[pairs[:, 0]], centers[pairs[:, 1]]], axis=1))
    crossed = np.sort(STRtree(segments).query(line, predicate="crosses"))
    if crossed.size == 0:
        return []
    edges = interior[crossed]
    total_length = float(shapely.length(shapely.linestrings(shapely.get_coordinates(line)))) or 1.0
    along = shapely.line_locate_point(line, shapely.points(geometry.edge_midpoint[edges]))
    stations = along / total_length
    order = np.argsort(stations, kind="stable")
    cells = geometry.edge_cells[edges]
    return [
        BarrierFace(cell_a=int(cells[k, 0]), cell_b=int(cells[k, 1]), s=float(stations[k]))
        for k in order
    ]
