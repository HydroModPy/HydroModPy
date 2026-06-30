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

import numpy as np

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


def _line_coords(line) -> np.ndarray:
    """Return the (n, 2) vertex coordinates of a shapely LineString."""
    return np.asarray(line.coords, dtype=float)[:, :2]


def barrier_faces_from_line(planar_mesh, line) -> list[BarrierFace]:
    """Return the interior mesh faces a barrier line crosses.

    For every interior edge (shared by exactly two cells) the segment is tested
    against the line; a crossing yields one ``BarrierFace`` carrying the two cell
    ids and the line position. Faces are returned ordered along the line.
    """
    from shapely.geometry import LineString

    verts = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    conn = np.asarray(planar_mesh.flat_connectivity, dtype=int)
    n_cells, nodes_per_cell = conn.shape

    edge_to_cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    for ci in range(n_cells):
        cell = conn[ci]
        for k in range(nodes_per_cell):
            a = int(cell[k])
            b = int(cell[(k + 1) % nodes_per_cell])
            edge_to_cells[(a, b) if a < b else (b, a)].append(ci)

    coords = _line_coords(line)
    total_len = float(LineString(coords).length) or 1.0

    faces: list[BarrierFace] = []
    for (a, b), cells in edge_to_cells.items():
        if len(cells) != 2:
            continue
        edge = LineString([verts[a], verts[b]])
        if not line.crosses(edge) and not line.intersects(edge):
            continue
        point = line.intersection(edge)
        if point.is_empty or point.geom_type != "Point":
            continue
        s = float(line.project(point)) / total_len
        ci, cj = sorted(cells)
        faces.append(BarrierFace(cell_a=int(ci), cell_b=int(cj), s=s))

    faces.sort(key=lambda f: f.s)
    return faces
