"""Read a triangulation from a gmsh ``.msh`` file (format 2.2, ASCII).

Vertices and triangles come from ``read_gmsh_2d_mesh``, so their order is
the one every planar mesh read from a file had so far. The line elements of
the named physical groups (``$PhysicalNames``) become the edge labels; a
line element of an unnamed group carries no label.

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
from shapely.geometry import Polygon

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import read_gmsh_2d_mesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh
from hydromodpy.spatial.mesh.request import InputTriangulation

__all__ = ["check_triangulation", "domain_polygon_of", "read_input_triangulation"]

logger = get_logger(__name__)

_LINE_ELEMENT = 1
"""Gmsh element type of a two-node line."""

_VERTEX_TOLERANCE = 1e-9
"""Distance below which two vertices, or a vertex and an edge, touch, relative to the extent."""

_POINTS_SHOWN = 5
"""Number of coordinates a message lists."""


def read_input_triangulation(path: str | Path) -> InputTriangulation:
    """Return the triangles of the ``.msh`` file at *path* and its labelled line edges."""
    source = Path(path)
    sections = _sections(source)
    _check_format(sections, source)
    mesh = read_gmsh_2d_mesh(source, cell_type="triangle")
    tags = _node_tags(sections["Nodes"], source)
    positions = {tag: index for index, tag in enumerate(tags)}
    names = _physical_line_names(sections.get("PhysicalNames", []))
    edges: dict[str, list[tuple[int, int]]] = {}
    for line in sections["Elements"][1:]:
        values = [int(token) for token in line.split()]
        element_type, n_tags = values[1], values[2]
        if element_type != _LINE_ELEMENT or n_tags < 1:
            continue
        name = names.get(values[3])
        if name is None:
            continue
        node_a, node_b = values[3 + n_tags : 5 + n_tags]
        edges.setdefault(name, []).append((positions[node_a], positions[node_b]))
    if len(tags) != mesh.n_nodes:
        raise MeshRequestError(
            f"{source}: {len(tags)} nodes in $Nodes, the mesh reader kept {mesh.n_nodes}"
        )
    check_triangulation(mesh.points_xy, mesh.connectivity, source=str(source))
    return InputTriangulation(
        vertices=mesh.points_xy,
        triangles=mesh.connectivity,
        edge_labels={
            name: np.asarray(pairs, dtype=np.int64).reshape(-1, 2) for name, pairs in edges.items()
        },
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


def _sections(path: Path) -> dict[str, list[str]]:
    """The non-empty lines of each ``$Name`` ... ``$EndName`` block, by name."""
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("$End"):
                current = None
            elif line.startswith("$"):
                current = sections.setdefault(line[1:], [])
            elif current is not None and line:
                current.append(line)
    for required in ("MeshFormat", "Nodes", "Elements"):
        if required not in sections:
            raise MeshRequestError(f"{path} has no ${required} section")
    return sections


def _check_format(sections: dict[str, list[str]], path: Path) -> None:
    """Refuse anything but an ASCII file of format 2.x."""
    header = sections["MeshFormat"][0].split()
    if len(header) < 2 or not header[0].startswith("2.") or header[1] != "0":
        raise MeshRequestError(
            f"{path} is gmsh format {' '.join(header)}; only ASCII format 2.2 is read"
        )


def _node_tags(lines: list[str], path: Path) -> list[int]:
    """Node tags in file order: a node's index is its position in the file."""
    count = int(lines[0])
    if len(lines) != count + 1:
        raise MeshRequestError(f"{path}: $Nodes announces {count} nodes, holds {len(lines) - 1}")
    return [int(line.split(maxsplit=1)[0]) for line in lines[1:]]


def _physical_line_names(lines: list[str]) -> dict[int, str]:
    """Names of the one-dimensional physical groups, by physical tag."""
    names: dict[int, str] = {}
    for line in lines[1:]:
        dim, tag, name = line.split(maxsplit=2)
        if int(dim) == 1:
            names[int(tag)] = name.strip().strip('"')
    return names
