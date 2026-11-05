"""The receiver graph of a mesh: which cell drains into which, and what accumulates downhill."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


def active_surface_mask(topography: Any, *, nodata_floor: float = -9000.0) -> np.ndarray:
    """Return True for cells with a finite, non-nodata surface elevation."""
    surface = np.asarray(topography, dtype=float).reshape(-1)
    return np.isfinite(surface) & (surface > float(nodata_floor))


def cell_adjacency_from_face_connectivity(
    face_node_connectivity: Any,
    *,
    n_cells: int | None = None,
) -> list[set[int]]:
    """Build a cell-neighbor graph from UGRID face-node connectivity."""
    connectivity = np.asarray(face_node_connectivity, dtype=int)
    if connectivity.ndim == 1:
        connectivity = connectivity.reshape(1, -1)
    n_cells_int = int(n_cells or connectivity.shape[0])
    adjacency = [set() for _ in range(n_cells_int)]
    edge_owners: dict[tuple[int, int], list[int]] = {}

    for cell_id, row in enumerate(connectivity[:n_cells_int]):
        nodes = [int(node) for node in np.asarray(row, dtype=int).reshape(-1) if int(node) >= 0]
        if len(nodes) < 2:
            continue
        for node_index, node_a in enumerate(nodes):
            node_b = nodes[(node_index + 1) % len(nodes)]
            if node_a == node_b:
                continue
            edge = tuple(sorted((int(node_a), int(node_b))))
            owners = edge_owners.setdefault(edge, [])
            for owner in owners:
                if owner == cell_id:
                    continue
                adjacency[cell_id].add(owner)
                adjacency[owner].add(cell_id)
            if cell_id not in owners:
                owners.append(cell_id)
    return adjacency


def domain_edge_cells(face_node_connectivity: Any, active: Any) -> np.ndarray:
    """Return the active cells holding a face edge no other active cell shares.

    The geometric boundary of the modeled domain, where water leaves the mesh.
    It is the seed set a priority flood needs to raise the closed depressions
    and nothing else.

    Read off the mesh rather than off the neighbor count: a degree below the
    maximum means "on the edge" only on a structured grid, and a Voronoi dual
    carries every degree from three upwards in its interior.
    """
    selected = np.asarray(active, dtype=bool).reshape(-1)
    rows = np.asarray(face_node_connectivity, dtype=np.int64)
    if rows.ndim == 1:
        rows = rows.reshape(1, -1)
    rows = rows[: selected.size]
    present = rows >= 0
    # Compact the nodes of each face to the front, keeping the ring order, so
    # the following node of slot j is slot (j + 1) modulo the face arity.
    ring = np.take_along_axis(rows, np.argsort(~present, axis=1, kind="stable"), axis=1)
    arity = present.sum(axis=1)
    slots = np.arange(rows.shape[1])
    following = np.take_along_axis(
        ring, np.mod(slots[None, :] + 1, np.maximum(arity, 1)[:, None]), axis=1
    )
    low = np.minimum(ring, following)
    high = np.maximum(ring, following)
    drawn = (slots[None, :] < arity[:, None]) & selected[:, None] & (low != high)
    key = low * (int(rows.max(initial=0)) + 1) + high
    _, inverse, counts = np.unique(key[drawn], return_inverse=True, return_counts=True)
    shared = np.zeros(key.shape, dtype=bool)
    shared[drawn] = counts[inverse] > 1
    return selected & (drawn & ~shared).any(axis=1)


def cell_centroids_from_mesh(
    vertices: Any,
    face_node_connectivity: Any,
) -> np.ndarray:
    """Return one XY centroid per mesh face."""
    points = np.asarray(vertices, dtype=float)
    connectivity = np.asarray(face_node_connectivity, dtype=int)
    if connectivity.ndim == 1:
        connectivity = connectivity.reshape(1, -1)
    valid = (connectivity >= 0) & (connectivity < points.shape[0])
    safe = np.where(valid, connectivity, 0)
    xy = points[safe, :2]
    finite = np.isfinite(xy) & valid[:, :, None]
    sums = np.where(finite, xy, 0.0).sum(axis=1)
    counts = finite.sum(axis=1)
    return np.where(counts > 0, sums / np.maximum(counts, 1), np.nan).astype("float64")


@dataclass(frozen=True)
class DownhillGraph:
    """Static steepest-descent receiver graph over a mesh surface.

    ``downstream`` maps each cell to its single receiver (-1 = outlet/none),
    ``order`` lists active cells by descending reference elevation, and
    ``active`` flags routable cells. Build once per mesh; the graph is
    independent of the routed values, so transient stacks reuse it.
    """

    downstream: np.ndarray
    order: np.ndarray
    active: np.ndarray


def build_downhill_graph(
    reference_values: Any,
    face_node_connectivity: Any,
    *,
    vertices: Any | None = None,
    centroids: Any | None = None,
    inactive_mask: Any | None = None,
    adjacency: list[set[int]] | None = None,
) -> DownhillGraph:
    """Build the steepest downhill receiver graph for a static surface.

    ``adjacency`` replaces the shared-edge neighbor graph derived from the face
    connectivity. Pass one to route over shared nodes instead, which is how a
    structured grid recovers its diagonal descents.

    ``centroids`` are the points ``reference_values`` were sampled at, used to
    normalize a drop into a slope. Without them the polygon centroid is derived
    from ``vertices``, which is the same point on a parallelogram cell and NOT
    on a Voronoi dual: there the generator seed carries the elevation while the
    vertex mean sits elsewhere, so the drop and the length would span two
    different segments and the ratio would be a slope of nothing.
    """
    reference = np.asarray(reference_values, dtype=float).reshape(-1)
    n_cells = int(reference.size)
    if inactive_mask is None:
        inactive = np.zeros(n_cells, dtype=bool)
    else:
        inactive = np.asarray(inactive_mask, dtype=bool).reshape(-1)
        if inactive.size != n_cells:
            raise ValueError(f"inactive_mask must have {n_cells} entries, got {inactive.size}.")
    if adjacency is not None and len(adjacency) != n_cells:
        raise ValueError(f"adjacency must have {n_cells} entries, got {len(adjacency)}.")

    active = (~inactive) & np.isfinite(reference)
    downstream = np.full(n_cells, -1, dtype=int)
    if not np.any(active):
        return DownhillGraph(downstream=downstream, order=np.empty(0, dtype=int), active=active)

    if adjacency is None:
        adjacency = cell_adjacency_from_face_connectivity(
            face_node_connectivity,
            n_cells=n_cells,
        )
    if centroids is not None:
        centroids = np.asarray(centroids, dtype=float)
        if centroids.ndim != 2 or centroids.shape != (n_cells, 2):
            raise ValueError(
                f"centroids must be ({n_cells}, 2), got {centroids.shape}. They are the points "
                "the reference values were sampled at, one per cell."
            )
    elif vertices is not None:
        centroids = cell_centroids_from_mesh(vertices, face_node_connectivity)
    if centroids is not None and (
        centroids.shape[0] != n_cells or not np.any(np.isfinite(centroids))
    ):
        centroids = None

    max_degree = max((len(cells) for cells in adjacency), default=0)
    neighbors = np.full((n_cells, max(max_degree, 1)), -1, dtype=int)
    for cell_id, cells in enumerate(adjacency):
        if cells:
            neighbors[cell_id, : len(cells)] = sorted(cells)

    ref_active = reference[active]
    ref_range = float(np.nanmax(ref_active) - np.nanmin(ref_active))
    tolerance = max(1.0e-9, 1.0e-9 * max(abs(ref_range), 1.0))

    clipped = np.clip(neighbors, 0, n_cells - 1)
    valid = (neighbors >= 0) & active[clipped] & active[:, None]
    drop = reference[:, None] - reference[clipped]
    valid &= np.isfinite(drop) & (drop > tolerance)
    score = drop
    if centroids is not None:
        pair_finite = np.isfinite(centroids).all(axis=1)[:, None] & np.isfinite(
            centroids[clipped]
        ).all(axis=2)
        delta = centroids[:, None, :] - centroids[clipped]
        distance = np.maximum(np.hypot(delta[..., 0], delta[..., 1]), 1.0e-12)
        score = np.where(pair_finite, drop / distance, drop)
    score = np.where(valid, score, -np.inf)
    best = np.argmax(score, axis=1)
    rows = np.arange(n_cells)
    has_receiver = score[rows, best] > 0.0
    downstream[has_receiver] = neighbors[rows, best][has_receiver]

    order_all = np.argsort(np.where(active, reference, -np.inf).astype(float, copy=False))[::-1]
    order = order_all[active[order_all]]
    return DownhillGraph(downstream=downstream, order=order, active=active)


def accumulate_on_downhill_graph(graph: DownhillGraph, local_values: Any) -> np.ndarray:
    """Accumulate positive sources along a prebuilt receiver graph.

    Accepts a single ``(n_cells,)`` field or a ``(time, n_cells)`` stack and
    returns the same leading shape. The graph traversal runs once with all
    timesteps carried as vectors, so a transient stack costs one pass.
    """
    local = np.asarray(local_values, dtype=float)
    single = local.ndim == 1
    stack = local.reshape(1, -1) if single else local
    n_cells = int(graph.active.size)
    if stack.ndim != 2 or stack.shape[1] != n_cells:
        raise ValueError(f"local_values must have {n_cells} cells, got shape {local.shape}.")
    if not np.any(graph.active):
        out = np.zeros(stack.shape, dtype="float64")
        return out[0] if single else out

    accumulated = np.where(
        graph.active[None, :] & np.isfinite(stack), np.maximum(stack, 0.0), 0.0
    ).astype("float64", copy=False)
    downstream = graph.downstream
    for cell_id in graph.order.tolist():
        target = int(downstream[cell_id])
        if target >= 0:
            accumulated[:, target] += accumulated[:, cell_id]
    accumulated[:, ~graph.active] = np.nan
    return accumulated[0] if single else accumulated


__all__ = [
    "DownhillGraph",
    "accumulate_on_downhill_graph",
    "active_surface_mask",
    "build_downhill_graph",
    "cell_adjacency_from_face_connectivity",
    "cell_centroids_from_mesh",
    "domain_edge_cells",
]
