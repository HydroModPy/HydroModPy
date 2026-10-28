"""Face family rows the mesh engines share: oriented edges, the table, the zones.

A family line lies on mesh edges. Each of its edges becomes one row with the
cell on the left of the oriented line as ``cell_a`` and the cell on the right as
``cell_b`` (``-1`` on the domain boundary, where the row is flipped so that
``cell_a`` is the cell). The rows of every family make one ``FaceFamilyTable``.
The regions the faces of a family cut live in ``cells/regions.py``.
The module lives above the engines, so the Voronoi engine reads these rows without
importing the families of the triangle engine.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.model.geometry import BOX_SIDES, DerivedGeometry, box_side_of_edges
from hydromodpy.spatial.mesh.model.planar_cell_mesh import FaceFamilyTable
from hydromodpy.spatial.mesh.request import MeshRequest

__all__ = [
    "EdgeLookup",
    "FamilyEdges",
    "box_side_edges",
    "edge_lookup",
    "face_table",
    "oriented_rows",
    "request_zone_names",
    "without_repeats",
]


@dataclass(frozen=True, eq=False)
class FamilyEdges:
    """The oriented mesh edges of one family, in line order.

    ``line`` is the source line of each row; ``forward`` is false where the row
    was flipped against its line to keep a cell on its left.
    """

    name: str
    node_a: np.ndarray
    node_b: np.ndarray
    cell_a: np.ndarray
    cell_b: np.ndarray
    zone_left: np.ndarray
    zone_right: np.ndarray
    line: np.ndarray
    forward: np.ndarray

    def line_vertices(self, line: int) -> np.ndarray:
        """The vertex ids along one source line, in the line direction."""
        rows = np.flatnonzero(self.line == line)
        start = np.where(self.forward[rows], self.node_a[rows], self.node_b[rows])
        stop = np.where(self.forward[rows], self.node_b[rows], self.node_a[rows])
        sequence = np.concatenate([start[:1], stop]) if rows.size else np.empty(0, np.int64)
        return without_repeats(sequence)


@dataclass(frozen=True, eq=False)
class EdgeLookup:
    """Directed edges of counter-clockwise triangles, keyed ``a * n_nodes + b``.

    The edge table of ``DerivedGeometry`` is undirected, so it cannot say which
    triangle lies on the left of ``a -> b``; this one can.
    """

    n_nodes: int
    keys: np.ndarray
    cells: np.ndarray
    ccw: np.ndarray

    def cell_left_of(self, node_a: np.ndarray, node_b: np.ndarray) -> np.ndarray:
        """The triangle on the left of each directed edge ``a -> b``, ``-1`` if none."""
        wanted = np.asarray(node_a, np.int64) * self.n_nodes + np.asarray(node_b, np.int64)
        position = np.minimum(np.searchsorted(self.keys, wanted), self.keys.size - 1)
        return np.where(self.keys[position] == wanted, self.cells[position], -1)

    def fan(self, start: int, pivot: int, stop: int) -> list[int]:
        """Triangles met turning clockwise around ``pivot``, from ``start`` on.

        ``start`` is the triangle left of an edge that ends at ``pivot``. The
        list holds the triangles after ``start`` up to the one left of
        ``pivot -> stop``; it is empty when the fan reaches the boundary first.
        """
        cells: list[int] = []
        current = start
        for _ in range(self.keys.size):
            corners = self.ccw[current].tolist()
            following = corners[(corners.index(pivot) + 1) % 3]
            if following == stop:
                return cells
            current = int(self.cell_left_of(np.array([following]), np.array([pivot]))[0])
            if current < 0:
                return []
            cells.append(current)
        return []


def edge_lookup(vertices: np.ndarray, triangles: np.ndarray) -> EdgeLookup:
    """Index the directed edges of the triangles taken counter-clockwise."""
    corners = vertices[triangles]
    cross = (corners[:, 1, 0] - corners[:, 0, 0]) * (corners[:, 2, 1] - corners[:, 0, 1]) - (
        corners[:, 1, 1] - corners[:, 0, 1]
    ) * (corners[:, 2, 0] - corners[:, 0, 0])
    ccw = np.where((cross < 0.0)[:, None], triangles[:, [0, 2, 1]], triangles)
    source = ccw.ravel()
    target = ccw[:, [1, 2, 0]].ravel()
    n_nodes = len(vertices)
    keys = source.astype(np.int64) * n_nodes + target
    order = np.argsort(keys, kind="stable")
    cells = np.repeat(np.arange(len(triangles), dtype=np.int64), 3)
    return EdgeLookup(n_nodes=n_nodes, keys=keys[order], cells=cells[order], ccw=ccw)


def without_repeats(values: np.ndarray) -> np.ndarray:
    """The values as int64, each run of equal neighbours kept once."""
    values = np.asarray(values, dtype=np.int64)
    if values.size == 0:
        return values
    return values[np.concatenate([[True], values[1:] != values[:-1]])]


def oriented_rows(
    name: str,
    lookup: EdgeLookup,
    edges: np.ndarray,
    line: np.ndarray,
    zone_left: np.ndarray,
    zone_right: np.ndarray,
) -> FamilyEdges:
    """Rows of oriented edges, flipped where only the right side is a cell."""
    edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    left = lookup.cell_left_of(edges[:, 0], edges[:, 1])
    right = lookup.cell_left_of(edges[:, 1], edges[:, 0])
    missing = (left < 0) & (right < 0)
    if np.any(missing):
        a, b = edges[np.flatnonzero(missing)[0]]
        raise MeshGenerationError(f"family {name!r}: edge ({a}, {b}) is not a triangle edge")
    forward = left >= 0
    return FamilyEdges(
        name=name,
        node_a=np.where(forward, edges[:, 0], edges[:, 1]),
        node_b=np.where(forward, edges[:, 1], edges[:, 0]),
        cell_a=np.where(forward, left, right),
        cell_b=np.where(forward, right, -1),
        zone_left=np.where(forward, zone_left, zone_right).astype(np.int32),
        zone_right=np.where(forward, zone_right, zone_left).astype(np.int32),
        line=np.asarray(line, dtype=np.int64),
        forward=forward,
    )


def request_zone_names(request: MeshRequest) -> tuple[str, ...]:
    """Sorted zone names of every family of the request."""
    names = {zone for family in request.lines for zone in (*family.zone_left, *family.zone_right)}
    return tuple(sorted(names))


def box_side_edges(
    vertices: np.ndarray, geometry: DerivedGeometry, lookup: EdgeLookup
) -> tuple[FamilyEdges, ...]:
    """Families ``boundary:<side>`` of the boundary edges on each side of the vertex box.

    The side of an edge is the one :func:`box_side_of_edges` gives it.
    """
    outer = np.flatnonzero(geometry.edge_cells[:, 1] < 0)
    pairs = geometry.edge_nodes[outer]
    side = box_side_of_edges(vertices, pairs[:, 0], pairs[:, 1])
    families = []
    for index, name in enumerate(BOX_SIDES):
        on_side = side == index
        if not np.any(on_side):
            continue
        unknown = np.full(int(on_side.sum()), -1, dtype=np.int32)
        families.append(
            oriented_rows(
                f"boundary:{name}",
                lookup,
                pairs[on_side],
                np.full(unknown.size, -1),
                unknown,
                unknown,
            )
        )
    return tuple(families)


def face_table(families: tuple[FamilyEdges, ...]) -> FaceFamilyTable | None:
    """The face family table of every family with at least one row."""
    present = [family for family in families if family.cell_a.size]
    if not present:
        return None
    return FaceFamilyTable.stack(
        [
            (
                family.name,
                {
                    "cell_a": family.cell_a,
                    "cell_b": family.cell_b,
                    "node_a": family.node_a,
                    "node_b": family.node_b,
                    "zone_left": family.zone_left,
                    "zone_right": family.zone_right,
                },
            )
            for family in present
        ]
    )
