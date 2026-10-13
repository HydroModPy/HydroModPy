"""Read a triangulation from a gmsh ``.msh`` file (format 2.2, ASCII).

Vertices and triangles come from ``read_gmsh_2d_mesh``, so their order is
the one every planar mesh read from a file had so far. The line elements of
the named physical groups (``$PhysicalNames``) become the edge labels; a
line element of an unnamed group carries no label.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from shapely.geometry import Polygon

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import read_gmsh_2d_mesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh
from hydromodpy.spatial.mesh.request import InputTriangulation

__all__ = ["domain_polygon_of", "read_input_triangulation"]

_LINE_ELEMENT = 1
"""Gmsh element type of a two-node line."""


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
    return InputTriangulation(
        vertices=mesh.points_xy,
        triangles=mesh.connectivity,
        edge_labels={
            name: np.asarray(pairs, dtype=np.int64).reshape(-1, 2) for name, pairs in edges.items()
        },
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
