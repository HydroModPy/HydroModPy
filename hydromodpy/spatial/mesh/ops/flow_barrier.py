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
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.strtree import STRtree

if TYPE_CHECKING:
    from shapely.geometry import LineString

    from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = [
    "BarrierFace",
    "barrier_faces_from_line",
    "crossed_edges",
    "cutoff_wall_faces",
    "downstream_of_wall",
    "lake_shore_faces",
    "mesh_footprint",
    "trace_end_gaps",
    "wall_leaks",
]


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
    edges = crossed_edges(geometry, cell_mesh.centers, line)
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


def crossed_edges(geometry: DerivedGeometry, centers: np.ndarray, line: LineString) -> np.ndarray:
    """Interior edge rows whose centre-to-centre segment *line* crosses, in edge order.

    On a grid, these faces are the staircase that separates the cells on
    either side of the line.
    """
    interior = np.flatnonzero(geometry.edge_cells[:, 1] >= 0)
    pairs = geometry.edge_cells[interior]
    segments = shapely.linestrings(np.stack([centers[pairs[:, 0]], centers[pairs[:, 1]]], axis=1))
    return interior[np.sort(STRtree(segments).query(line, predicate="crosses"))]


def downstream_of_wall(line: LineString, points: np.ndarray) -> np.ndarray:
    """Whether each point lies across a wall that has the lake on its left.

    The side is read at the nearest point of the wall, against the local
    direction of the wall there, so a curved wall is followed. A point whose
    nearest point of the wall is one of its ends lies round the wall, not
    across it, and a point on the wall is on neither side: neither is downstream.
    """
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    along = shapely.line_locate_point(line, shapely.points(points))
    step = 1.0e-6 * max(line.length, 1.0)
    before = shapely.get_coordinates(
        shapely.line_interpolate_point(line, np.maximum(along - step, 0.0))
    )
    after = shapely.get_coordinates(
        shapely.line_interpolate_point(line, np.minimum(along + step, line.length))
    )
    foot = shapely.get_coordinates(shapely.line_interpolate_point(line, along))
    tangent = after - before
    offset = points - foot
    across = tangent[:, 0] * offset[:, 1] - tangent[:, 1] * offset[:, 0] < 0.0
    tip = 1.0e-9 * max(line.length, 1.0)
    return across & (along > tip) & (along < line.length - tip)


def lake_shore_faces(
    cell_mesh: PlanarCellMesh, line: LineString, lake_cells: np.ndarray
) -> np.ndarray:
    """Interior edges between a lake cell and a cell downstream of the wall.

    *line* is a wall with the lake on its left. Every face of the lake cell set
    whose outer cell lies downstream of the wall belongs to the wall: barring
    them all leaves no cell between the reservoir and the wall.
    """
    geometry = cell_mesh.geometry
    lake = np.zeros(geometry.n_cells, dtype=bool)
    lake[np.asarray(lake_cells, dtype=np.int64)] = True
    pairs = geometry.edge_cells
    interior = pairs[:, 1] >= 0
    first_in = lake[pairs[:, 0]]
    second_in = np.where(interior, lake[np.maximum(pairs[:, 1], 0)], False)
    shore = np.flatnonzero(interior & (first_in != second_in))
    outer = np.where(first_in[shore], pairs[shore, 1], pairs[shore, 0])
    return shore[downstream_of_wall(line, cell_mesh.centers[outer])]


def cutoff_wall_faces(
    cell_mesh: PlanarCellMesh,
    line: LineString,
    lake_cells: np.ndarray,
    trace: LineString | None = None,
) -> list[BarrierFace]:
    """The faces of a lake cutoff wall: its shore faces and the faces it crosses.

    *line* is the wall laid on the shore, lake on its left. Along the shore the
    wall is every face between a lake cell and a cell downstream of it, so it
    hugs the lake cell set; on a regular grid that is the staircase around the
    overlap cells. The faces *line* separates are barred too: they carry the
    wings and joints, and close the fence where the cells round a corner of
    the shore. A face between two lake cells is never barred. ``s`` is the
    position along *trace* (the declared trace, whose vertices carry the
    depths), *line* when none is given.
    """
    geometry = cell_mesh.geometry
    lake = np.zeros(geometry.n_cells, dtype=bool)
    lake[np.asarray(lake_cells, dtype=np.int64)] = True
    edges = set(lake_shore_faces(cell_mesh, line, lake_cells).tolist())
    lookup = {(a, b): k for k, (a, b) in enumerate(geometry.edge_cells.tolist()) if b >= 0}
    for face in barrier_faces_from_line(cell_mesh, line):
        if not (lake[face.cell_a] and lake[face.cell_b]):
            edges.add(lookup[(face.cell_a, face.cell_b)])
    if not edges:
        return []
    rows = np.array(sorted(edges), dtype=np.int64)
    station_line = line if trace is None else trace
    total = float(station_line.length) or 1.0
    along = shapely.line_locate_point(station_line, shapely.points(geometry.edge_midpoint[rows]))
    stations = along / total
    cells = geometry.edge_cells[rows]
    return [
        BarrierFace(
            cell_a=int(cells[k, 0]),
            cell_b=int(cells[k, 1]),
            s=float(stations[k]),
            length=float(geometry.edge_length[rows[k]]),
        )
        for k in np.argsort(stations, kind="stable")
    ]


def wall_leaks(
    cell_mesh: PlanarCellMesh,
    line: LineString,
    lake_cells: np.ndarray,
    barred: list[BarrierFace],
    *,
    reach: float,
) -> np.ndarray:
    """Lake-side cells the downstream side reaches without crossing a barred face.

    The walk starts from every non-lake cell downstream of *line* (lake on its
    left) within *reach* [m] of it, and moves through the faces left open
    between cells within that reach. A cell whose nearest point of the wall is
    an end of the wall is outside the walk, so the walk never goes round a
    wing. A closed wall returns no cell.
    """
    geometry = cell_mesh.geometry
    n_cells = geometry.n_cells
    centres = shapely.points(cell_mesh.centers)
    along = shapely.line_locate_point(line, centres)
    tip = 1.0e-9 * max(line.length, 1.0)
    walk = (shapely.distance(centres, line) <= reach) & (along > tip) & (along < line.length - tip)
    lake = np.zeros(n_cells, dtype=bool)
    lake[np.asarray(lake_cells, dtype=np.int64)] = True
    downstream = downstream_of_wall(line, cell_mesh.centers) & ~lake
    pairs = geometry.edge_cells[geometry.edge_cells[:, 1] >= 0]
    keys = pairs[:, 0] * n_cells + pairs[:, 1]
    closed = np.array([face.cell_a * n_cells + face.cell_b for face in barred], dtype=np.int64)
    open_pairs = pairs[~np.isin(keys, closed) & walk[pairs[:, 0]] & walk[pairs[:, 1]]]
    graph = coo_matrix(
        (np.ones(len(open_pairs)), (open_pairs[:, 0], open_pairs[:, 1])), shape=(n_cells, n_cells)
    )
    component = connected_components(graph, directed=False)[1]
    reached = np.isin(component, component[walk & downstream])
    return np.flatnonzero(reached & walk & ~downstream)


def mesh_footprint(cell_mesh: PlanarCellMesh) -> shapely.Geometry:
    """Return the union of the cell polygons (the planar model domain)."""
    rows = np.asarray(cell_mesh.connectivity_rows)
    verts = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    polygons = [shapely.Polygon(verts[row[row >= 0]]) for row in rows]
    return shapely.union_all(polygons)


def trace_end_gaps(footprint: shapely.Geometry, line: LineString) -> tuple[float, float]:
    """Return the open length [m] left at the start and at the end of a trace.

    The open length is the distance from the trace end to the domain outline,
    when that end lies inside the domain. Flow can go around the barrier
    through this gap. An end on or outside the outline leaves no gap.
    """
    coords = shapely.get_coordinates(line)
    outline = footprint.boundary
    gaps = []
    for xy in (coords[0], coords[-1]):
        point = shapely.Point(float(xy[0]), float(xy[1]))
        inside = footprint.contains(point)
        gaps.append(float(outline.distance(point)) if inside else 0.0)
    return gaps[0], gaps[1]
