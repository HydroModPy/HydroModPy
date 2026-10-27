"""Map a vector barrier line onto the faces of a cell mesh.

A flow barrier (MODFLOW 6 HFB) is a thin vertical low-permeability wall placed on
the SHARED FACE between two adjacent cells (DIS / DISV / DISU). This module turns
a polyline (a dam axis, a cutoff-wall / grout-curtain trace) into the list of
cell-pair faces it bars, each tagged with the line position so a per-segment
depth can be interpolated. On an engine whose faces follow the lines, these are
the faces of the ``barriers`` family that lie on the line; on a staircase engine,
the faces the line crosses.

The faces of a lake cutoff wall laid on the shore are built from these by the
MODFLOW 6 builders (``solver/modflow6/builders/_lake_geometry.py``).

Reference: the HFB6 package, Langevin et al. (2017), MODFLOW 6 TM 6-A55.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely.strtree import STRtree

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY

if TYPE_CHECKING:
    from shapely.geometry import LineString

    from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = [
    "ON_CENTRE_SHARE",
    "ON_LINE_SHARE",
    "SIDE_SHIFT_SHARE",
    "BarrierFace",
    "barrier_edges",
    "barrier_faces_from_line",
    "crossed_edges",
]

logger = get_logger(__name__)


ON_LINE_SHARE = 0.5
"""A family face lies on a barrier line when its midpoint is within this share of
its length from the line: the faces along a lake shore follow the resampled ring,
a chord of the shore the line was laid on."""

ON_CENTRE_SHARE = 1.0e-9
"""A cell centre lies on a barrier line when it is closer than this share of the
median centre-to-centre link."""

SIDE_SHIFT_SHARE = 1.0e-6
"""How far left a line through cell centres is tested, as a share of the median link."""


@dataclass(frozen=True)
class BarrierFace:
    """One mesh face crossed by a barrier line.

    ``cell_a`` / ``cell_b`` are the two adjacent cell2d ids sharing the face,
    ``cell_a < cell_b``; ``s`` is the normalized position [0, 1] of the crossing
    along the line, used to interpolate a per-vertex depth onto the face.
    ``length`` is the face length [m], used to weight the face conductance.
    """

    cell_a: int
    cell_b: int
    s: float
    length: float = 0.0


def barrier_faces_from_line(cell_mesh: PlanarCellMesh, line: LineString) -> list[BarrierFace]:
    """Return the interior mesh faces that make a CONTINUOUS cut along a barrier line.

    The faces are those of :func:`barrier_edges`: the barrier family faces on
    the line where the mesh follows it, the faces it crosses elsewhere. ``s``
    is the edge midpoint's normalized position along the line, for per-vertex
    depth interpolation. Faces are returned ordered along the line, ties in
    edge order.
    """
    geometry = cell_mesh.geometry
    edges = barrier_edges(cell_mesh, line)
    if edges.size == 0:
        return []
    total_length = float(shapely.length(shapely.linestrings(shapely.get_coordinates(line)))) or 1.0
    along = shapely.line_locate_point(line, shapely.points(geometry.edge_midpoint[edges]))
    stations = along / total_length
    order = np.argsort(stations, kind="stable")
    cells = geometry.edge_cells[edges]
    return [
        BarrierFace(
            cell_a=int(cells[k, 0]),
            cell_b=int(cells[k, 1]),
            s=float(stations[k]),
            length=float(geometry.edge_length[edges[k]]),
        )
        for k in order
    ]


def barrier_edges(cell_mesh: PlanarCellMesh, line: LineString) -> np.ndarray:
    """Interior edge rows a barrier line bars, sorted.

    On an engine whose faces follow the lines, they are the faces of the
    ``barriers`` family that lie on *line* (:data:`ON_LINE_SHARE`), plus the
    faces *line* crosses (:func:`crossed_edges`) where no family face covers
    it: a stretch the engine could not follow, within one face length of its
    ends, or a mesh without the family. On a staircase engine they are the
    faces *line* crosses.
    """
    geometry = cell_mesh.geometry
    crossed = crossed_edges(geometry, cell_mesh.centers, line)
    on_line = _family_edges_on_line(cell_mesh, line)
    if not on_line.size:
        return crossed
    gaps = _uncovered(line, cell_mesh, on_line)
    if not gaps:
        return on_line
    crossing = shapely.intersection(
        shapely.linestrings(
            np.stack(
                [
                    cell_mesh.centers[geometry.edge_cells[crossed, 0]],
                    cell_mesh.centers[geometry.edge_cells[crossed, 1]],
                ],
                axis=1,
            )
        ),
        line,
    )
    station = shapely.line_locate_point(line, shapely.point_on_surface(crossing))
    margin = float(np.median(geometry.edge_length[on_line]))
    in_gap = np.zeros(crossed.size, dtype=bool)
    for low, high in gaps:
        in_gap |= (station >= low - margin) & (station <= high + margin)
    return np.union1d(on_line, crossed[in_gap])


def _family_edges_on_line(cell_mesh: PlanarCellMesh, line: LineString) -> np.ndarray:
    """Interior edge rows of the barrier family faces that lie on *line*, sorted.

    None on a mesh whose faces do not follow the lines (a staircase).
    """
    table = cell_mesh.face_families
    if table is None or not cell_mesh.qa.declarations.get("exact_faces", False):
        return np.empty(0, dtype=np.int64)
    rows = cell_mesh.face_rows(BARRIER_FAMILY) & (table.cell_b >= 0)
    if not rows.any():
        return np.empty(0, dtype=np.int64)
    geometry = cell_mesh.geometry
    pairs = np.sort(np.column_stack([table.cell_a[rows], table.cell_b[rows]]), axis=1)
    edges = _edges_of_pairs(geometry, pairs)
    edges = np.unique(edges[edges >= 0])
    gap = shapely.distance(shapely.points(geometry.edge_midpoint[edges]), line)
    return edges[gap <= ON_LINE_SHARE * geometry.edge_length[edges]]


def _uncovered(
    line: LineString, cell_mesh: PlanarCellMesh, edges: np.ndarray
) -> list[tuple[float, float]]:
    """The stretches ``(start, end)`` [m along *line*] that no face of *edges* covers.

    A face covers the stretch between the projections of its two nodes on the
    line. Stretches shorter than a thousandth of the median face are dropped.
    """
    geometry = cell_mesh.geometry
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    nodes = geometry.edge_nodes[edges]
    ends = shapely.line_locate_point(line, shapely.points(vertices[nodes.ravel()])).reshape(-1, 2)
    spans = np.sort(ends, axis=1)
    spans = spans[np.argsort(spans[:, 0], kind="stable")]
    slack = 1.0e-3 * float(np.median(geometry.edge_length[edges]))
    gaps: list[tuple[float, float]] = []
    reached = 0.0
    for low, high in spans.tolist():
        if low - reached > slack:
            gaps.append((reached, low))
        reached = max(reached, high)
    if line.length - reached > slack:
        gaps.append((reached, float(line.length)))
    return gaps


def _edges_of_pairs(geometry: DerivedGeometry, pairs: np.ndarray) -> np.ndarray:
    """Edge row of each sorted cell pair ``(a, b)``, ``-1`` when the cells share no edge."""
    n_cells = np.int64(geometry.n_cells)
    keys = geometry.edge_cells[:, 0] * n_cells + geometry.edge_cells[:, 1]
    order = np.argsort(keys, kind="stable")
    probe = pairs[:, 0] * n_cells + pairs[:, 1]
    position = np.minimum(np.searchsorted(keys, probe, sorter=order), keys.size - 1)
    found = keys[order[position]] == probe
    return np.where(found, order[position], -1)


def crossed_edges(geometry: DerivedGeometry, centers: np.ndarray, line: LineString) -> np.ndarray:
    """Interior edge rows whose centre-to-centre segment *line* crosses, in edge order.

    On a grid, these faces are the staircase that separates the cells on
    either side of the line. A line through cell centres lies along their
    segments or touches them at an end, and crosses none there: it would bar
    nothing. It is then tested :data:`SIDE_SHIFT_SHARE` of a link to its left,
    which bars the faces on that side of the centres.
    """
    interior = np.flatnonzero(geometry.edge_cells[:, 1] >= 0)
    if not interior.size:
        return interior
    pairs = geometry.edge_cells[interior]
    ends = np.stack([centers[pairs[:, 0]], centers[pairs[:, 1]]], axis=1)
    segments = shapely.linestrings(ends)
    link = float(np.median(np.linalg.norm(ends[:, 1] - ends[:, 0], axis=1)))
    on_line = shapely.dwithin(shapely.points(centers), line, ON_CENTRE_SHARE * link)
    probe: shapely.Geometry = line
    if on_line.any():
        shift = SIDE_SHIFT_SHARE * link
        logger.info(
            "A barrier line runs through %d cell centres: its faces are taken %.2g m to its left.",
            int(on_line.sum()),
            shift,
        )
        probe = shapely.offset_curve(line, shift)
    return interior[np.sort(STRtree(segments).query(probe, predicate="crosses"))]
