"""Geometry derived once from a planar cell mesh: areas, edges, adjacency.

Every quantity is computed with vectorized numpy on the ``-1`` padded
connectivity, the format of the Zarr store and of ``core.drainage.descent``. Edges are
keyed by their two vertex ids, never by coordinates, so the topology does not
depend on rounding.

This module is the one home of the plane geometry of cells: the padded rows,
the area, the polygon of a cell, the edge between two vertices or two cells,
the side of the vertex box a boundary edge lies on, and the rings of a polygon.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely.geometry import LineString

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

__all__ = [
    "BOX_SIDES",
    "VERTEX_MERGE_M",
    "DerivedGeometry",
    "box_side_of_edges",
    "cell_areas",
    "cell_polygons",
    "derive_geometry",
    "derive_geometry_from_rows",
    "padded_rows",
    "polygon_rings",
    "vertex_keys",
]

VERTEX_MERGE_M = 1.0e-3
"""Two cell vertices closer than this [m] are one vertex."""

BOX_SIDES = ("west", "east", "south", "north")
"""The sides of the vertex box, in the order a boundary edge on two sides takes them."""

_PLANAR_TYPES = frozenset({CellType.TRIANGLE, CellType.QUADRILATERAL, CellType.POLYGON})


@dataclass(frozen=True, eq=False)
class DerivedGeometry:
    """Areas, area centroids, edge table and CSR adjacency of a planar mesh.

    ``edge_nodes`` rows hold ``node_a < node_b`` and are sorted by that pair.
    ``edge_cells`` rows hold ``cell_a < cell_b`` on an interior edge and
    ``(cell, -1)`` on the domain boundary. The adjacency is the CSR graph of the
    interior edges, neighbors sorted ascending.
    """

    padded_connectivity: np.ndarray
    areas: np.ndarray
    area_centroids: np.ndarray
    edge_nodes: np.ndarray
    edge_cells: np.ndarray
    edge_length: np.ndarray
    edge_midpoint: np.ndarray
    adjacency_indptr: np.ndarray
    adjacency_indices: np.ndarray
    n_nodes: int

    @property
    def n_cells(self) -> int:
        """Number of cells."""
        return int(self.areas.size)

    @functools.cached_property
    def _node_keys(self) -> np.ndarray:
        """One sorted int64 key per edge, ``node_a * n_nodes + node_b``."""
        return self.edge_nodes[:, 0] * np.int64(self.n_nodes) + self.edge_nodes[:, 1]

    @functools.cached_property
    def _interior_cell_keys(self) -> tuple[np.ndarray, np.ndarray]:
        """Sorted ``cell_a * n_cells + cell_b`` keys of the interior edges, and their edge ids."""
        interior = np.flatnonzero(self.edge_cells[:, 1] >= 0)
        keys = self.edge_cells[interior, 0] * np.int64(self.n_cells) + self.edge_cells[interior, 1]
        order = np.argsort(keys, kind="stable")
        return keys[order], interior[order]

    def edge_ids(self, node_a: np.ndarray, node_b: np.ndarray) -> np.ndarray:
        """Return the id of the edge joining each pair of vertices, ``-1`` where none does.

        The two vertices of a pair may come in either order.
        """
        a = np.asarray(node_a, dtype=np.int64)
        b = np.asarray(node_b, dtype=np.int64)
        low, high = np.minimum(a, b), np.maximum(a, b)
        keys = self._node_keys
        if keys.size == 0:
            return np.full(low.shape, -1, dtype=np.int64)
        probe = low * np.int64(self.n_nodes) + high
        position = np.minimum(np.searchsorted(keys, probe), keys.size - 1)
        found = (keys[position] == probe) & (low >= 0) & (high < self.n_nodes)
        return np.where(found, position, -1)

    def edge_between(self, cell_a: np.ndarray, cell_b: np.ndarray) -> np.ndarray:
        """Return the id of the interior edge two cells share, ``-1`` where they share none.

        The two cells of a pair may come in either order. Two cells that share
        several edges give the one with the smallest id.
        """
        a = np.asarray(cell_a, dtype=np.int64)
        b = np.asarray(cell_b, dtype=np.int64)
        keys, edges = self._interior_cell_keys
        if keys.size == 0:
            return np.full(a.shape, -1, dtype=np.int64)
        probe = np.minimum(a, b) * np.int64(self.n_cells) + np.maximum(a, b)
        position = np.minimum(np.searchsorted(keys, probe), keys.size - 1)
        found = (
            (keys[position] == probe)
            & (a != b)
            & (np.minimum(a, b) >= 0)
            & (np.maximum(a, b) < self.n_cells)
        )
        return np.where(found, edges[position], -1)

    def neighbours(self, cell: int) -> np.ndarray:
        """Return the sorted ids of the cells sharing a face with ``cell``."""
        start, stop = self.adjacency_indptr[cell], self.adjacency_indptr[cell + 1]
        return self.adjacency_indices[start:stop]

    def adjacency_sets(self) -> list[set[int]]:
        """Return one neighbor set per cell, for legacy callers only."""
        rows = np.split(self.adjacency_indices, self.adjacency_indptr[1:-1])
        return [set(row.tolist()) for row in rows]


def padded_rows(connectivity: np.ndarray | Sequence[np.ndarray], *, n_nodes: int) -> np.ndarray:
    """Return cell rows as one int64 table, each missing slot set to ``-1``.

    ``connectivity`` is a dense ``(n_cells, k)`` table or one node array per
    cell. A negative or non-finite entry, or a node id outside ``[0, n_nodes)``,
    is missing. A dense table keeps its slots in place; the nodes of a per-cell
    array are packed to the left of its row.
    """
    if isinstance(connectivity, np.ndarray) and connectivity.ndim == 2:
        table = connectivity
        if table.dtype.kind == "f":
            table = np.where(np.isfinite(table), table, -1)
        table = table.astype(np.int64)
        return np.where((table >= 0) & (table < n_nodes), table, -1)
    cells = [np.asarray(cell).reshape(-1) for cell in connectivity]
    owner = np.repeat(np.arange(len(cells)), [cell.size for cell in cells])
    nodes = np.concatenate(cells) if cells else np.empty(0, dtype=np.int64)
    if nodes.dtype.kind == "f":
        finite = np.isfinite(nodes)
        owner, nodes = owner[finite], nodes[finite]
    nodes = nodes.astype(np.int64)
    usable = (nodes >= 0) & (nodes < n_nodes)
    owner, nodes = owner[usable], nodes[usable]
    lengths = np.bincount(owner, minlength=len(cells))
    table = np.full((len(cells), int(lengths.max(initial=0))), -1, dtype=np.int64)
    starts = np.cumsum(lengths) - lengths
    table[owner, np.arange(nodes.size) - starts[owner]] = nodes
    return table


def _mesh_rows(mesh: HydroMesh) -> np.ndarray:
    """Return the cells of a planar mesh as an int64 array padded with ``-1``."""
    if mesh.ndim != 2:
        raise ValueError(f"a planar mesh needs 2-column vertices, got {mesh.ndim}")
    unsupported = [b.cell_type.value for b in mesh.cell_blocks if b.cell_type not in _PLANAR_TYPES]
    if unsupported:
        raise ValueError(f"not a planar cell type: {unsupported}")
    blocks = [padded_rows(block.connectivity, n_nodes=mesh.n_nodes) for block in mesh.cell_blocks]
    width = max(block.shape[1] for block in blocks)
    return np.vstack(
        [np.pad(b, ((0, 0), (0, width - b.shape[1])), constant_values=-1) for b in blocks]
    )


def _next_corner(padded: np.ndarray) -> np.ndarray:
    """Return, for each padded slot, the column of the next corner of its cell."""
    lengths = (padded >= 0).sum(axis=1)
    cols = np.arange(padded.shape[1])[None, :]
    return np.where(cols + 1 < lengths[:, None], cols + 1, 0)


def _corner_crosses(
    vertices: np.ndarray, padded: np.ndarray, next_col: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return the first corner, each corner and the next one relative to it, and their cross product.

    Coordinates are taken relative to each cell's first corner: in Lambert-93 the
    raw cross products reach 1e12 m2 and would cancel to a few meters squared.
    """
    valid = padded >= 0
    rows = np.arange(padded.shape[0])[:, None]
    nxt = padded[rows, next_col]
    origin = vertices[padded[:, 0]]
    p = np.where(valid[..., None], vertices[np.where(valid, padded, 0)], 0.0) - origin[:, None]
    q = np.where(valid[..., None], vertices[np.where(valid, nxt, 0)], 0.0) - origin[:, None]
    cross = np.where(valid, p[..., 0] * q[..., 1] - q[..., 0] * p[..., 1], 0.0)
    return origin, p, q, cross


def cell_areas(vertices: np.ndarray, padded: np.ndarray) -> np.ndarray:
    """Return the shoelace area [m2] of each row of vertex ids padded with ``-1``.

    The corners of a row are packed to its left, as the run store keeps them.
    The sum is taken relative to the first corner of each cell, which keeps the
    precision of projected coordinates. A row of fewer than three corners has
    an area of zero. ``vertices`` may carry a third column, which is ignored.
    """
    rows = np.asarray(padded, dtype=np.int64)
    if rows.ndim != 2 or rows.shape[1] == 0:
        return np.zeros(len(rows))
    xy = np.asarray(vertices, dtype=np.float64)[:, :2]
    cross = _corner_crosses(xy, rows, _next_corner(rows))[3]
    return 0.5 * np.abs(cross.sum(axis=1))


def _areas_and_centroids(
    vertices: np.ndarray, padded: np.ndarray, next_col: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Shoelace area and area centroid of every padded row."""
    origin, p, q, cross = _corner_crosses(vertices, padded, next_col)
    signed_double = cross.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cx = ((p[..., 0] + q[..., 0]) * cross).sum(axis=1) / (3.0 * signed_double)
        cy = ((p[..., 1] + q[..., 1]) * cross).sum(axis=1) / (3.0 * signed_double)
    centroids = origin + np.column_stack([cx, cy])
    return 0.5 * np.abs(signed_double), centroids


def _edge_table(
    padded: np.ndarray, next_col: np.ndarray, n_nodes: int
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``edge_nodes`` and ``edge_cells`` from the padded rows.

    A corner repeated in a row gives a zero-length side with no face; it is
    dropped here and counted by the QA.
    """
    rows = np.arange(padded.shape[0])[:, None]
    node_a = padded
    node_b = padded[rows, next_col]
    keep = (node_a >= 0) & (node_a != node_b)
    owner = np.broadcast_to(rows, padded.shape)[keep]
    lo = np.minimum(node_a, node_b)[keep]
    hi = np.maximum(node_a, node_b)[keep]
    keys = lo * np.int64(n_nodes) + hi
    unique_keys, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    if counts.size and counts.max() > 2:
        bad = unique_keys[counts > 2][0]
        raise ValueError(
            f"topology error: edge ({bad // n_nodes}, {bad % n_nodes}) is shared by "
            f"{int(counts.max())} cells; a planar edge has at most two"
        )
    order = np.argsort(inverse, kind="stable")
    owners = owner[order]
    starts = np.cumsum(counts) - counts
    first = owners[starts]
    second = np.where(counts == 2, owners[np.minimum(starts + 1, owners.size - 1)], -1)
    twice = (counts == 2) & (first == second)
    if np.any(twice):
        raise ValueError(f"topology error: cell {int(first[twice][0])} uses one edge twice")
    interior = second >= 0
    cell_a = np.where(interior, np.minimum(first, second), first)
    cell_b = np.where(interior, np.maximum(first, second), -1)
    edge_nodes = np.column_stack([unique_keys // n_nodes, unique_keys % n_nodes])
    return edge_nodes, np.column_stack([cell_a, cell_b]).astype(np.int64)


def _csr_adjacency(edge_cells: np.ndarray, n_cells: int) -> tuple[np.ndarray, np.ndarray]:
    """Return the CSR graph of the interior edges, neighbors sorted ascending."""
    inner = edge_cells[edge_cells[:, 1] >= 0]
    src = np.concatenate([inner[:, 0], inner[:, 1]])
    dst = np.concatenate([inner[:, 1], inner[:, 0]])
    keys = np.unique(src * np.int64(n_cells) + dst)
    rows = keys // n_cells
    indptr = np.zeros(n_cells + 1, dtype=np.int64)
    np.cumsum(np.bincount(rows, minlength=n_cells), out=indptr[1:])
    return indptr, (keys % n_cells).astype(np.int64)


def derive_geometry_from_rows(vertices: np.ndarray, padded: np.ndarray) -> DerivedGeometry:
    """Derive the geometry of cells given as rows of vertex ids padded with ``-1``.

    ``vertices`` holds at least two columns (x, y); a third one is ignored. This
    is the core of :func:`derive_geometry`, for a reader that holds the stored
    connectivity and no ``HydroMesh``. Raises ``ValueError`` on a topology error.
    """
    rows = np.asarray(padded, dtype=np.int64)
    xy = np.asarray(vertices, dtype=np.float64)[:, :2]
    next_col = _next_corner(rows)
    areas, centroids = _areas_and_centroids(xy, rows, next_col)
    edge_nodes, edge_cells = _edge_table(rows, next_col, xy.shape[0])
    start = xy[edge_nodes[:, 0]]
    stop = xy[edge_nodes[:, 1]]
    delta = stop - start
    indptr, indices = _csr_adjacency(edge_cells, int(rows.shape[0]))
    return DerivedGeometry(
        padded_connectivity=rows.astype(np.int32),
        areas=areas,
        area_centroids=centroids,
        edge_nodes=edge_nodes,
        edge_cells=edge_cells,
        edge_length=np.hypot(delta[:, 0], delta[:, 1]),
        edge_midpoint=start + 0.5 * delta,
        adjacency_indptr=indptr,
        adjacency_indices=indices,
        n_nodes=int(xy.shape[0]),
    )


def derive_geometry(mesh: HydroMesh) -> DerivedGeometry:
    """Derive areas, centroids, edges and adjacency of a planar ``HydroMesh``.

    Raises ``ValueError`` on a topology error: an edge shared by more than two
    cells, or a cell that uses one edge twice.
    """
    return derive_geometry_from_rows(np.asarray(mesh.vertices), _mesh_rows(mesh))


def box_side_of_edges(vertices: np.ndarray, node_a: np.ndarray, node_b: np.ndarray) -> np.ndarray:
    """Return, per edge, the index in :data:`BOX_SIDES` of the side of the vertex box it lies on.

    An edge lies on a side when its midpoint is within ``1e-8`` of the larger
    span of the box (``1e-9`` m at least) from that side's line. An edge on two
    sides, at a corner, takes the first in :data:`BOX_SIDES`. ``-1`` for an edge
    on no side. The caller picks the boundary edges.
    """
    xy = np.asarray(vertices, dtype=np.float64)[:, :2]
    low = xy.min(axis=0)
    high = xy.max(axis=0)
    tolerance = max(1.0e-9, 1.0e-8 * max(*(high - low), 1.0))
    middle = 0.5 * (xy[np.asarray(node_a)] + xy[np.asarray(node_b)])
    sides = np.full(middle.shape[0], -1, dtype=np.int64)
    for index, (axis, value) in enumerate(((0, low[0]), (0, high[0]), (1, low[1]), (1, high[1]))):
        sides[(sides < 0) & (np.abs(middle[:, axis] - value) <= tolerance)] = index
    return sides


def polygon_rings(*geometries: BaseGeometry | None) -> list[LineString]:
    """Return every ring of the polygons as lines, exterior first, part after part.

    A multi-part geometry gives the rings of each part in order. ``None`` is
    skipped.
    """
    rings: list[LineString] = []
    for geometry in geometries:
        if geometry is None:
            continue
        for part in shapely.get_parts(geometry):
            rings.append(LineString(part.exterior.coords))
            rings.extend(LineString(ring.coords) for ring in part.interiors)
    return rings


def cell_polygons(
    vertices: np.ndarray,
    connectivity: np.ndarray | Sequence[np.ndarray],
    *,
    keep_invalid: bool = False,
) -> np.ndarray:
    """Return one Shapely polygon per mesh cell, ``None`` where the cell is degenerate.

    ``connectivity`` is a dense ``(n_cells, k)`` table or one node array per
    cell, read as :func:`padded_rows` reads it: a negative, non-finite or
    out-of-range entry is dropped and the other nodes keep their order. A cell
    of fewer than three nodes is ``None``. An invalid or empty polygon is
    ``None`` too, unless ``keep_invalid``, which keeps it as built.
    """
    points = np.asarray(vertices, dtype=float)[:, :2]
    rows = padded_rows(connectivity, n_nodes=points.shape[0])
    rows = np.take_along_axis(rows, np.argsort(rows < 0, axis=1, kind="stable"), axis=1)
    sizes = (rows >= 0).sum(axis=1)
    polygons = np.full(rows.shape[0], None, dtype=object)
    # Shapely builds the polygons of one node count in a single C call. Cell by
    # cell costs six Python-level shapely calls per cell: on the Nancon at 25 m,
    # 243 552 cells took 14.6 s that way and 0.5 s this way.
    for size in np.unique(sizes[sizes >= 3]):
        cells = np.flatnonzero(sizes == size)
        polygons[cells] = shapely.polygons(points[rows[cells, :size]])
    if not keep_invalid:
        polygons[~shapely.is_valid(polygons) | shapely.is_empty(polygons)] = None
    return polygons


def vertex_keys(xy: np.ndarray) -> np.ndarray:
    """Return one int64 key per point on a grid of :data:`VERTEX_MERGE_M`: equal keys are one vertex.

    Coordinates are rounded half to even. Raises ``MeshGenerationError`` when a
    point lies 2^31 steps or more from the origin, where keys would collide.
    """
    grid = np.rint(np.asarray(xy, dtype=float).reshape(-1, 2) / VERTEX_MERGE_M)
    if np.abs(grid).max(initial=0.0) >= 2.0**31:
        raise MeshGenerationError("the local frame spans more than 2^31 mm along an axis")
    cells = grid.astype(np.int64)
    return cells[:, 0] * np.int64(1 << 32) + (cells[:, 1] + np.int64(1 << 31))
