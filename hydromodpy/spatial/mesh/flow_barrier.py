"""Map a vector barrier line onto the planar-mesh faces it crosses.

A flow barrier (MODFLOW 6 HFB) is a thin vertical low-permeability wall placed on
the SHARED FACE between two adjacent cells, so it needs no grid refinement and is
grid-independent (DIS / DISV / DISU). This module turns a polyline (a dam axis, a
cutoff-wall / grout-curtain trace) into the list of cell-pair faces it crosses,
each tagged with the line position so a per-segment depth can be interpolated.

Reference: the HFB6 package, Langevin et al. (2017), MODFLOW 6 TM 6-A55.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from shapely.geometry import LineString

    from hydromodpy.spatial.mesh.hydro_mesh import HydroMesh

__all__ = ["BarrierFace", "barrier_faces_from_line"]


@dataclass(frozen=True)
class BarrierFace:
    """One mesh face crossed by a barrier line.

    ``cell_a`` / ``cell_b`` are the two adjacent cell2d ids sharing the face;
    ``s`` is the normalized position [0, 1] of the crossing along the line, used
    to interpolate a per-vertex depth onto the face.
    """

    cell_a: int
    cell_b: int
    s: float


def _line_coords(line: LineString) -> np.ndarray:
    """Return the (n, 2) vertex coordinates of a shapely LineString."""
    return np.asarray(line.coords, dtype=float)[:, :2]


def barrier_faces_from_line(planar_mesh: HydroMesh, line: LineString) -> list[BarrierFace]:
    """Return the interior mesh faces that make a CONTINUOUS cut along a barrier line.

    A face (interior edge shared by two cells) is barred when the trace passes
    BETWEEN the two cells, i.e. it crosses the segment joining their centroids.
    This selects the full chain of cell-pair faces the line separates, so the
    barrier is a single connected fence with no leak paths -- unlike barring only
    the edges the trace clips, which leaves gaps where a cell the line passes
    through stays connected to both sides. The criterion is mesh-adaptive (no
    corridor width) and shape-agnostic (any polyline), and it never trips on a
    trace collinear with a mesh edge. ``s`` is the edge midpoint's normalized
    position along the line, for per-vertex depth interpolation. Faces are
    returned ordered along the line.
    """
    from shapely.geometry import LineString, Point

    verts = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    conn = planar_mesh.flat_connectivity  # rectangular array or ragged POLYGON tuple

    edge_to_cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    centroids: dict[int, np.ndarray] = {}
    for ci in range(len(conn)):
        cell = np.asarray(conn[ci], dtype=int)
        centroids[ci] = verts[cell].mean(axis=0)
        arity = len(cell)
        for k in range(arity):
            a = int(cell[k])
            b = int(cell[(k + 1) % arity])
            edge_to_cells[(a, b) if a < b else (b, a)].append(ci)

    total_len = float(LineString(_line_coords(line)).length) or 1.0

    faces: list[BarrierFace] = []
    for (a, b), cells in edge_to_cells.items():
        if len(cells) != 2:
            continue
        ci, cj = sorted(cells)
        centroid_seg = LineString([centroids[ci], centroids[cj]])
        if not line.crosses(centroid_seg):
            continue
        edge_mid = (verts[a] + verts[b]) / 2.0
        s = float(line.project(Point(float(edge_mid[0]), float(edge_mid[1])))) / total_len
        faces.append(BarrierFace(cell_a=int(ci), cell_b=int(cj), s=s))

    faces.sort(key=lambda f: f.s)
    return faces
