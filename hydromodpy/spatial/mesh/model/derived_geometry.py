"""Geometry derived once from a planar cell mesh: areas, edges, adjacency.

Every quantity is computed with vectorised numpy on the ``-1`` padded
connectivity, the format of the Zarr store and of ``core.descent``. Edges are
keyed by their two vertex ids, never by coordinates, so the topology does not
depend on rounding.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

__all__ = ["DerivedGeometry", "derive_geometry", "derive_geometry_from_rows"]

_PLANAR_TYPES = frozenset({CellType.TRIANGLE, CellType.QUADRILATERAL, CellType.POLYGON})


@dataclass(frozen=True, eq=False)
class DerivedGeometry:
    """Areas, area centroids, edge table and CSR adjacency of a planar mesh.

    ``edge_nodes`` rows hold ``node_a < node_b`` and are sorted by that pair.
    ``edge_cells`` rows hold ``cell_a < cell_b`` on an interior edge and
    ``(cell, -1)`` on the domain boundary. The adjacency is the CSR graph of the
    interior edges, neighbours sorted ascending.
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

    @property
    def n_cells(self) -> int:
        """Number of cells."""
        return int(self.areas.size)

    def neighbours(self, cell: int) -> np.ndarray:
        """Return the sorted ids of the cells sharing a face with ``cell``."""
        start, stop = self.adjacency_indptr[cell], self.adjacency_indptr[cell + 1]
        return self.adjacency_indices[start:stop]

    def adjacency_sets(self) -> list[set[int]]:
        """Return one neighbour set per cell, for legacy callers only."""
        rows = np.split(self.adjacency_indices, self.adjacency_indptr[1:-1])
        return [set(row.tolist()) for row in rows]


def _padded_block(block: CellBlock) -> np.ndarray:
    """Return one block as an int64 ``(n, k)`` array padded with ``-1``."""
    if not block.cell_type.is_ragged:
        return np.asarray(block.connectivity, dtype=np.int64)
    cells = block.connectivity
    lengths = np.fromiter((cell.size for cell in cells), dtype=np.int64, count=len(cells))
    padded = np.full((len(cells), int(lengths.max(initial=0))), -1, dtype=np.int64)
    if lengths.size:
        rows = np.repeat(np.arange(lengths.size), lengths)
        starts = np.cumsum(lengths) - lengths
        cols = np.arange(int(lengths.sum())) - np.repeat(starts, lengths)
        padded[rows, cols] = np.concatenate(cells)
    return padded


def _padded_rows(mesh: HydroMesh) -> np.ndarray:
    """Return the cells of a planar mesh as an int64 array padded with ``-1``."""
    if mesh.ndim != 2:
        raise ValueError(f"a planar mesh needs 2-column vertices, got {mesh.ndim}")
    unsupported = [b.cell_type.value for b in mesh.cell_blocks if b.cell_type not in _PLANAR_TYPES]
    if unsupported:
        raise ValueError(f"not a planar cell type: {unsupported}")
    blocks = [_padded_block(block) for block in mesh.cell_blocks]
    width = max(block.shape[1] for block in blocks)
    return np.vstack(
        [np.pad(b, ((0, 0), (0, width - b.shape[1])), constant_values=-1) for b in blocks]
    )


def _next_corner(padded: np.ndarray) -> np.ndarray:
    """Return, for each padded slot, the column of the next corner of its cell."""
    lengths = (padded >= 0).sum(axis=1)
    cols = np.arange(padded.shape[1])[None, :]
    return np.where(cols + 1 < lengths[:, None], cols + 1, 0)


def _areas_and_centroids(
    vertices: np.ndarray, padded: np.ndarray, next_col: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Shoelace area and area centroid of every padded row.

    Coordinates are taken relative to each cell's first corner: in Lambert-93 the
    raw cross products reach 1e12 m2 and would cancel to a few metres squared.
    """
    valid = padded >= 0
    rows = np.arange(padded.shape[0])[:, None]
    nxt = padded[rows, next_col]
    origin = vertices[padded[:, 0]]
    p = np.where(valid[..., None], vertices[np.where(valid, padded, 0)], 0.0) - origin[:, None]
    q = np.where(valid[..., None], vertices[np.where(valid, nxt, 0)], 0.0) - origin[:, None]
    cross = np.where(valid, p[..., 0] * q[..., 1] - q[..., 0] * p[..., 1], 0.0)
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
    """Return the CSR graph of the interior edges, neighbours sorted ascending."""
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
    )


def derive_geometry(mesh: HydroMesh) -> DerivedGeometry:
    """Derive areas, centroids, edges and adjacency of a planar ``HydroMesh``.

    Raises ``ValueError`` on a topology error: an edge shared by more than two
    cells, or a cell that uses one edge twice.
    """
    return derive_geometry_from_rows(np.asarray(mesh.vertices), _padded_rows(mesh))
