"""Read a triangulation from a gmsh ``.msh`` file (format 2.2, ASCII).

The file is read once, by ``read_gmsh_2d_mesh``, after a look at its format
line. Vertices and triangles keep the order of that reader, the one every
planar mesh read from a file had so far. The line elements of the named
physical groups (``$PhysicalNames``) become the edge labels; a line element of
an unnamed group carries no label. A file the reader refuses is refused with
its reason.

``domain_polygon_from_mesh`` gives the outline of any planar mesh from its
boundary edges, which clips the Voronoi dual of a triangulation.

The triangles are checked before use. A T-junction, a vertex lying inside an
edge of a triangle that does not hold it, leaves boundary edges inside the
domain, so no flow crosses there: it is refused with its coordinates. Two
vertices closer than a tolerance are reported, since they cut the same crack.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import MultiPolygon, Polygon

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.mesh.io.msh import msh_format, read_gmsh_2d_mesh
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.request import InputTriangulation

__all__ = [
    "check_triangulation",
    "domain_polygon_from_mesh",
    "domain_polygon_of",
    "read_input_triangulation",
]

logger = get_logger(__name__)

_VERTEX_TOLERANCE = 1e-9
"""Distance below which two vertices, or a vertex and an edge, touch, relative to the extent."""

_POINTS_SHOWN = 5
"""Number of coordinates a message lists."""


def read_input_triangulation(path: str | Path) -> InputTriangulation:
    """Return the triangles of the ``.msh`` file at *path* and its labeled line edges."""
    source = Path(path)
    _check_format(source)
    try:
        mesh = read_gmsh_2d_mesh(source, cell_type="triangle")
    except ValueError as exc:
        raise MeshRequestError(f"{source} cannot be read as a triangulation: {exc}") from exc
    check_triangulation(mesh.points_xy, mesh.connectivity, source=str(source))
    return InputTriangulation(
        vertices=mesh.points_xy,
        triangles=mesh.connectivity,
        edge_labels=dict(mesh.line_groups),
    )


def check_triangulation(vertices: np.ndarray, triangles: np.ndarray, *, source: str) -> None:
    """Refuse a T-junction and warn on duplicate vertices of a triangulation.

    The tolerance is :data:`_VERTEX_TOLERANCE` times the diagonal of the vertex
    bounds. ``source`` names the mesh in the messages.
    """
    points = np.asarray(vertices, dtype=float)
    cells = np.asarray(triangles, dtype=np.int64)
    extent = float(np.hypot(*(points.max(axis=0) - points.min(axis=0))))
    tolerance = _VERTEX_TOLERANCE * max(extent, 1.0)

    pairs = cKDTree(points).query_pairs(tolerance, output_type="ndarray")
    if len(pairs):
        logger.warning(
            "%s: %d pairs of vertices lie within %.3g m of each other, first at %s. "
            "Two cells that meet there share no face, so no flow crosses between them.",
            source,
            len(pairs),
            tolerance,
            _coordinates(points[pairs[:, 0]]),
        )

    edges = np.sort(cells[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = unique[counts == 1]
    nodes = np.unique(boundary)
    segments = shapely.linestrings(points[boundary])
    node_index, edge_index = shapely.STRtree(segments).query(
        shapely.points(points[nodes]), predicate="dwithin", distance=tolerance
    )
    vertex = nodes[node_index]
    ends = boundary[edge_index]
    at_end = (np.linalg.norm(points[ends[:, 0]] - points[vertex], axis=1) <= tolerance) | (
        np.linalg.norm(points[ends[:, 1]] - points[vertex], axis=1) <= tolerance
    )
    hanging = np.unique(vertex[~at_end])
    if hanging.size:
        raise MeshRequestError(
            f"{source}: {hanging.size} vertices lie inside an edge of a triangle that does "
            f"not hold them (T-junctions), at {_coordinates(points[hanging])}. The edge is "
            "then a boundary inside the domain, closed to flow. Split the edge at the vertex "
            "in the mesh generator."
        )


def _coordinates(points: np.ndarray) -> str:
    """The first coordinates of ``points``, written for a message."""
    shown = ", ".join(f"({x:.3f}, {y:.3f})" for x, y in points[:_POINTS_SHOWN].tolist())
    return (
        shown if len(points) <= _POINTS_SHOWN else f"{shown} and {len(points) - _POINTS_SHOWN} more"
    )


def domain_polygon_of(triangulation: InputTriangulation) -> Polygon:
    """The polygon the triangles cover, holes included, from their boundary edges."""
    mesh = HydroMesh(
        vertices=np.asarray(triangulation.vertices),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(triangulation.triangles)),),
    )
    domain = domain_polygon_from_mesh(mesh)
    if not isinstance(domain, Polygon):
        raise MeshRequestError("the triangulation read covers more than one polygon")
    return domain


def domain_polygon_from_mesh(planar_mesh: HydroMesh) -> Polygon | MultiPolygon:
    """Reconstruct the meshed-domain outline from a planar mesh's boundary edges.

    A boundary edge belongs to exactly one cell; polygonizing those edges yields
    the outer polygon (with interior holes), which clips the Voronoi boundary
    cells. Works for any cell arity (triangles, quads, or n-gons).
    """
    from collections import defaultdict

    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    verts = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    edge_count: dict[tuple[int, int], int] = defaultdict(int)
    for row in planar_mesh.flat_connectivity:
        cell = row[row >= 0]
        k = len(cell)
        for i in range(k):
            a, b = int(cell[i]), int(cell[(i + 1) % k])
            edge_count[(min(a, b), max(a, b))] += 1
    lines = [LineString([verts[a], verts[b]]) for (a, b), n in edge_count.items() if n == 1]
    polys = list(polygonize(unary_union(lines)))
    if not polys:
        raise ValueError("could not reconstruct a domain polygon from mesh boundary edges")
    outer = max(polys, key=lambda p: p.area)
    holes = [p for p in polys if p is not outer and outer.contains(p.representative_point())]
    if holes:
        outer = Polygon(outer.exterior.coords, [h.exterior.coords for h in holes])
    return outer


def _check_format(path: Path) -> None:
    """Refuse a file without a ``$MeshFormat`` section, or not ASCII of format 2.x."""
    header = msh_format(path)
    if header is None:
        raise MeshRequestError(f"{path} has no $MeshFormat section")
    tokens = header.split()
    if len(tokens) < 2 or not tokens[0].startswith("2.") or tokens[1] != "0":
        raise MeshRequestError(
            f"{path} is gmsh format {' '.join(tokens)}; only ASCII format 2.2 is read"
        )
