"""Pure helpers for drain budgets and mesh routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

DRAIN_BUDGET_KEYS = ("drn", "drain", "drains", "DRN", "DRAINS")


def find_drain_budget_key(mapping: Any) -> str | None:
    """Return the first stored drain-budget key found in a mapping/group."""
    for key in DRAIN_BUDGET_KEYS:
        try:
            if key in mapping:
                return key
        except TypeError:
            return None
    return None


def _positive_outflow_from_signed(signed: np.ndarray) -> np.ndarray:
    """Sum signed ``(time, layer, cell)`` budgets into positive per-cell outflow.

    The all-positive fallback (budgets stored with outflow-positive sign) is
    decided independently per timestep, matching the historical per-field call.
    """
    finite = np.isfinite(signed) & (signed > -9000.0)
    positive_outflow = np.where(finite, np.maximum(-signed, 0.0), 0.0)
    has_finite = finite.any(axis=(1, 2))
    has_outflow = (positive_outflow > 0.0).any(axis=(1, 2))
    has_positive = ((signed > 0.0) & finite).any(axis=(1, 2))
    has_negative = ((signed < 0.0) & finite).any(axis=(1, 2))
    fallback = has_finite & ~has_outflow & has_positive & ~has_negative
    if np.any(fallback):
        positive_signed = np.where(finite, signed, 0.0)
        positive_outflow = np.where(fallback[:, None, None], positive_signed, positive_outflow)
    return positive_outflow.sum(axis=1).astype("float64", copy=False)


def drain_budget_to_positive_outflow(
    component_field: Any,
    *,
    n_cells: int | None = None,
) -> np.ndarray:
    """Convert a signed drain budget to positive per-cell outflow."""
    field = np.asarray(component_field, dtype=float)
    if field.ndim == 0:
        field = field.reshape(1)

    n_cells_int = int(n_cells or 0)
    if n_cells_int > 0 and field.size % n_cells_int == 0:
        signed = field.reshape(-1, n_cells_int)
    elif field.ndim == 1:
        signed = field.reshape(1, field.size)
    elif field.ndim == 2:
        signed = field
    else:
        signed = field.reshape(field.shape[0], -1)

    return _positive_outflow_from_signed(signed[None])[0]


def drain_budget_stack_to_positive_outflow(
    component_stack: Any,
    *,
    n_cells: int,
) -> np.ndarray:
    """Convert a signed ``(time, ...)`` drain budget stack to positive outflow.

    Returns a ``(time, n_cells)`` array; layers are summed per timestep.
    """
    stack = np.asarray(component_stack, dtype=float)
    if stack.ndim == 2:
        stack = stack[:, None, :]
    elif stack.ndim != 3:
        raise ValueError(f"Expected a (time, ...) budget stack, got shape {stack.shape}")
    n_cells_int = int(n_cells)
    per_step = stack.shape[1] * stack.shape[2]
    if n_cells_int > 0 and per_step % n_cells_int == 0:
        stack = stack.reshape(stack.shape[0], -1, n_cells_int)
    return _positive_outflow_from_signed(stack)


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
    inactive_mask: Any | None = None,
) -> DownhillGraph:
    """Build the steepest downhill receiver graph for a static surface."""
    reference = np.asarray(reference_values, dtype=float).reshape(-1)
    n_cells = int(reference.size)
    if inactive_mask is None:
        inactive = np.zeros(n_cells, dtype=bool)
    else:
        inactive = np.asarray(inactive_mask, dtype=bool).reshape(-1)
        if inactive.size != n_cells:
            raise ValueError(f"inactive_mask must have {n_cells} entries, got {inactive.size}.")

    active = (~inactive) & np.isfinite(reference)
    downstream = np.full(n_cells, -1, dtype=int)
    if not np.any(active):
        return DownhillGraph(downstream=downstream, order=np.empty(0, dtype=int), active=active)

    adjacency = cell_adjacency_from_face_connectivity(
        face_node_connectivity,
        n_cells=n_cells,
    )
    centroids = None
    if vertices is not None:
        centroids = cell_centroids_from_mesh(vertices, face_node_connectivity)
        if centroids.shape[0] != n_cells or not np.any(np.isfinite(centroids)):
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


def accumulate_downhill_on_mesh(
    local_values: Any,
    reference_values: Any,
    face_node_connectivity: Any,
    *,
    vertices: Any | None = None,
    inactive_mask: Any | None = None,
) -> np.ndarray:
    """Accumulate per-cell source values along the steepest downhill mesh path."""
    local = np.asarray(local_values, dtype=float).reshape(-1)
    reference = np.asarray(reference_values, dtype=float).reshape(-1)
    if local.size != reference.size:
        raise ValueError(
            "local_values and reference_values must have the same number of cells "
            f"({local.size} != {reference.size})."
        )
    graph = build_downhill_graph(
        reference,
        face_node_connectivity,
        vertices=vertices,
        inactive_mask=inactive_mask,
    )
    return accumulate_on_downhill_graph(graph, local)


__all__ = [
    "DRAIN_BUDGET_KEYS",
    "DownhillGraph",
    "accumulate_downhill_on_mesh",
    "accumulate_on_downhill_graph",
    "active_surface_mask",
    "build_downhill_graph",
    "cell_adjacency_from_face_connectivity",
    "cell_centroids_from_mesh",
    "drain_budget_stack_to_positive_outflow",
    "drain_budget_to_positive_outflow",
    "find_drain_budget_key",
]
