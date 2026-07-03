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
    """Return the interior mesh faces a barrier line crosses.

    For every interior edge (shared by exactly two cells) the segment is tested
    against the line. A transversal crossing yields one ``BarrierFace`` carrying
    the two cell ids and the line position (the nearest crossing point when the
    line re-crosses the same face). A line that only touches a face at an endpoint
    is not a barrier there and is skipped. A trace collinear with a mesh edge is
    geometrically ambiguous and raises, asking the user to offset the trace off
    the mesh edges. Faces are returned ordered along the line.
    """
    from shapely.geometry import LineString

    verts = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    conn = planar_mesh.flat_connectivity  # rectangular array or ragged POLYGON tuple

    edge_to_cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    for ci in range(len(conn)):
        cell = np.asarray(conn[ci], dtype=int)
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
        edge = LineString([verts[a], verts[b]])
        inter = line.intersection(edge)
        if inter.is_empty:
            continue
        gtype = inter.geom_type
        if gtype in ("LineString", "MultiLineString"):
            raise ValueError(
                "Flow-barrier trace is collinear with the mesh edge between cells "
                f"{sorted(cells)}; offset the trace off the mesh edges so each crossing "
                "is a clean transversal intersection."
            )
        if not line.crosses(edge):
            # Endpoint-only touch (the line stops on the face without entering the
            # neighbour cell): no barrier belongs on this face.
            continue
        if gtype == "Point":
            points = [inter]
        elif gtype == "MultiPoint":
            points = list(inter.geoms)
        else:
            continue
        s = min(float(line.project(point)) for point in points) / total_len
        ci, cj = sorted(cells)
        faces.append(BarrierFace(cell_a=int(ci), cell_b=int(cj), s=s))

    faces.sort(key=lambda f: f.s)
    return faces
