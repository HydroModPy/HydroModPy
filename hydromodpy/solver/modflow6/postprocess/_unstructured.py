"""Unstructured-mesh adjacency and flux accumulation helpers."""

from __future__ import annotations

import numpy as np

from ._models import NODATA, FlowPostprocessModel


def build_unstructured_cell_adjacency(model: FlowPostprocessModel) -> list[set[int]]:
    """Return cell-to-cell adjacency for one unstructured planar mesh."""
    n_cells = int(getattr(model, "ncpl", 0) or getattr(model.solver_mesh, "n_cells", 0))
    adjacency: list[set[int]] = [set() for _ in range(n_cells)]
    support = getattr(model, "runtime_mesh_support", None)
    if support is not None:
        edge_cell_a = np.asarray(getattr(support, "edge_cell_a", ()), dtype=int).reshape(-1)
        edge_cell_b = np.asarray(getattr(support, "edge_cell_b", ()), dtype=int).reshape(-1)
        for cell_a, cell_b in zip(edge_cell_a.tolist(), edge_cell_b.tolist(), strict=False):
            if int(cell_a) < 0 or int(cell_b) < 0:
                continue
            if int(cell_a) >= n_cells or int(cell_b) >= n_cells:
                continue
            adjacency[int(cell_a)].add(int(cell_b))
            adjacency[int(cell_b)].add(int(cell_a))
        if any(neighbors for neighbors in adjacency):
            return adjacency

    planar_mesh = getattr(model.solver_mesh, "planar_mesh", None)
    if planar_mesh is None:
        return adjacency

    edge_owner: dict[tuple[int, int], int] = {}
    cell_offset = 0
    for block in tuple(getattr(planar_mesh, "cell_blocks", ()) or ()):
        connectivity = np.asarray(getattr(block, "connectivity", ()), dtype=int)
        if connectivity.ndim != 2:
            continue
        for local_index, node_ids in enumerate(connectivity.tolist()):
            cell_id = int(cell_offset + local_index)
            if cell_id >= n_cells:
                break
            nodes = np.asarray(node_ids, dtype=int).reshape(-1)
            if nodes.size < 3:
                continue
            for node_index in range(int(nodes.size)):
                node_a = int(nodes[node_index])
                node_b = int(nodes[(node_index + 1) % int(nodes.size)])
                edge = tuple(sorted((node_a, node_b)))
                owner = edge_owner.get(edge)
                if owner is None:
                    edge_owner[edge] = cell_id
                    continue
                if int(owner) == cell_id:
                    continue
                adjacency[cell_id].add(int(owner))
                adjacency[int(owner)].add(cell_id)
        cell_offset += int(connectivity.shape[0])
    return adjacency


def accumulate_unstructured_cell_values(
    model: FlowPostprocessModel,
    *,
    local_values: np.ndarray,
    reference_values: np.ndarray,
    inactive_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Accumulate one per-cell source field along a downhill mesh graph."""
    local = np.asarray(local_values, dtype=float).reshape(-1)
    reference = np.asarray(reference_values, dtype=float).reshape(-1)
    n_cells = int(getattr(model, "ncpl", 0) or getattr(model.solver_mesh, "n_cells", 0))
    if local.size != n_cells or reference.size != n_cells:
        raise ValueError(
            "Unstructured accumulation requires local_values/reference_values "
            f"with {n_cells} entries."
        )

    if inactive_mask is None:
        mask = np.zeros(n_cells, dtype=bool)
    else:
        mask = np.asarray(inactive_mask, dtype=bool).reshape(-1)
        if mask.size != n_cells:
            raise ValueError(f"inactive_mask must have {n_cells} entries, got {mask.size}.")

    active = (~mask) & np.isfinite(reference)
    if not np.any(active):
        return np.zeros(n_cells, dtype=float)

    adjacency = build_unstructured_cell_adjacency(model)
    centroids: np.ndarray | None = None
    try:
        centroids = np.asarray(model.solver_mesh.cell_centroids(), dtype=float).reshape(n_cells, 2)
    except Exception:
        centroids = None

    ref_active = reference[active]
    ref_range = float(np.nanmax(ref_active) - np.nanmin(ref_active)) if ref_active.size > 0 else 0.0
    tolerance = max(1.0e-9, 1.0e-9 * max(abs(ref_range), 1.0))
    downstream = np.full(n_cells, -1, dtype=int)

    for cell_id in np.flatnonzero(active).tolist():
        best_neighbor = -1
        best_score = 0.0
        cell_ref = float(reference[cell_id])
        for neighbor in adjacency[int(cell_id)]:
            if neighbor < 0 or neighbor >= n_cells or not bool(active[neighbor]):
                continue
            neighbor_ref = float(reference[int(neighbor)])
            drop = cell_ref - neighbor_ref
            if not np.isfinite(drop) or drop <= tolerance:
                continue
            score = drop
            if centroids is not None:
                delta_x = float(centroids[cell_id, 0] - centroids[int(neighbor), 0])
                delta_y = float(centroids[cell_id, 1] - centroids[int(neighbor), 1])
                distance = max((delta_x * delta_x + delta_y * delta_y) ** 0.5, 1.0e-12)
                score = drop / distance
            if score > best_score:
                best_score = float(score)
                best_neighbor = int(neighbor)
        downstream[int(cell_id)] = int(best_neighbor)

    clean_local = np.where(
        active & np.isfinite(local) & (local > float(NODATA)),
        np.maximum(local, 0.0),
        0.0,
    )
    accumulated = np.zeros(n_cells, dtype=float)
    order = np.argsort(np.where(active, reference, -np.inf).astype(float, copy=False))[::-1]
    for cell_id in order.tolist():
        if not bool(active[int(cell_id)]):
            continue
        accumulated[int(cell_id)] += float(clean_local[int(cell_id)])
        target = int(downstream[int(cell_id)])
        if target >= 0:
            accumulated[target] += float(accumulated[int(cell_id)])

    accumulated[~active] = np.nan
    return accumulated
