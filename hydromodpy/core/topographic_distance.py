"""Downslope topographic distance on a static receiver graph.

The distance from a cell is the length of its descent path down to the first
cell of a target mask, measured centroid to centroid along the receiver graph.
It is a quasi-metric: ``d(a, b)`` and ``d(b, a)`` differ, and that asymmetry is
what lets a cost compare an excess of simulated stream against a missing one.

The graph and the edge lengths depend only on the conditioned surface, never on
the routed values, so one metric serves every calibration trial. Only the target
mask changes from one trial to the next, for one ``O(n_cells)`` pass each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.core.field_routing import (
    DownhillGraph,
    build_downhill_graph,
    cell_centroids_from_mesh,
)


@dataclass(frozen=True)
class DownslopeMetric:
    """Static receiver graph plus the length of every receiver link."""

    graph: DownhillGraph
    edge_length: np.ndarray
    centroids: np.ndarray
    diagonal_neighbors: bool


@dataclass(frozen=True, slots=True)
class DownslopeDistanceSummary:
    """Support-restricted statistics of one downslope distance field.

    ``n_support`` splits exactly into ``n_reached`` (the descent met the
    target), ``n_unreachable`` (it ended without one) and ``n_undefined`` (the
    cell is outside the active surface). The three counts are distinct on
    purpose: an unreachable cell is a conditioning defect, an undefined one is
    not part of the problem.
    """

    mean_m: float
    max_m: float
    n_support: int
    n_reached: int
    n_unreachable: int
    n_undefined: int


def _shared_node_adjacency(
    face_node_connectivity: Any,
    *,
    n_cells: int,
) -> list[set[int]]:
    """Build a cell-neighbor graph from shared nodes instead of shared edges.

    On a structured quad grid this is the eight-neighbor D8 neighborhood: two
    diagonal cells share a single node and no edge, so the shared-edge builder
    of ``field_routing`` never pairs them.
    """
    connectivity = np.asarray(face_node_connectivity, dtype=int)
    if connectivity.ndim == 1:
        connectivity = connectivity.reshape(1, -1)
    rows = connectivity[:n_cells]

    nodes_per_face = (rows >= 0).sum(axis=1)
    if not np.all(nodes_per_face == 4):
        raise ValueError(
            "diagonal_neighbors=True needs a structured quad mesh, but "
            f"{int(np.sum(nodes_per_face != 4))} of {rows.shape[0]} faces do not have four "
            "nodes. On an unstructured mesh a shared node without a shared edge is a mesh "
            "degeneracy, not a diagonal."
        )

    cells = np.repeat(np.arange(rows.shape[0], dtype=int), rows.shape[1])
    nodes = rows.reshape(-1)
    keep = nodes >= 0
    cells = cells[keep]
    nodes = nodes[keep]
    order = np.argsort(nodes, kind="stable")
    cells = cells[order]
    nodes = nodes[order]

    adjacency: list[set[int]] = [set() for _ in range(n_cells)]
    for group in np.split(cells, np.flatnonzero(np.diff(nodes)) + 1):
        incident = group.tolist()
        for position, cell_id in enumerate(incident):
            for other in incident[position + 1 :]:
                adjacency[cell_id].add(other)
                adjacency[other].add(cell_id)
    return adjacency


def build_downslope_metric(
    reference_values: Any,
    face_node_connectivity: Any,
    *,
    vertices: Any,
    inactive_mask: Any | None = None,
    diagonal_neighbors: bool = False,
) -> DownslopeMetric:
    """Build the receiver graph and its edge lengths for a static surface.

    ``vertices`` is required: an edge length is a centroid-to-centroid
    distance, which is the D8 convention of the paper on an isotropic grid and
    is exact by construction on an unstructured mesh.
    """
    if vertices is None:
        raise ValueError(
            "build_downslope_metric needs vertices: an edge length is a centroid distance."
        )
    reference = np.asarray(reference_values, dtype=float).reshape(-1)
    n_cells = int(reference.size)

    adjacency = None
    if diagonal_neighbors:
        adjacency = _shared_node_adjacency(face_node_connectivity, n_cells=n_cells)

    graph = build_downhill_graph(
        reference,
        face_node_connectivity,
        vertices=vertices,
        inactive_mask=inactive_mask,
        adjacency=adjacency,
    )

    centroids = cell_centroids_from_mesh(vertices, face_node_connectivity)
    if centroids.shape[0] != n_cells:
        raise ValueError(
            f"the mesh carries {centroids.shape[0]} faces but the surface has {n_cells} values."
        )

    has_receiver = graph.downstream >= 0
    edge_length = np.full(n_cells, np.nan, dtype="float64")
    if np.any(has_receiver):
        delta = centroids[has_receiver] - centroids[graph.downstream[has_receiver]]
        edge_length[has_receiver] = np.hypot(delta[:, 0], delta[:, 1])
    degenerate = has_receiver & ~np.isfinite(edge_length)
    if np.any(degenerate):
        raise ValueError(
            f"{int(degenerate.sum())} routed cells have a non-finite centroid distance: "
            "the mesh geometry is degenerate and no length can be measured along them."
        )

    return DownslopeMetric(
        graph=graph,
        edge_length=edge_length,
        centroids=centroids,
        diagonal_neighbors=bool(diagonal_neighbors),
    )


def downslope_distance_to_mask(metric: DownslopeMetric, target_mask: Any) -> np.ndarray:
    """Path length down to the first target cell, per cell.

    Returns float64 ``(n_cells,)``: ``0`` on target cells, a finite length when
    the descent reaches a target, ``inf`` when it ends without one, and ``nan``
    outside the active surface. An empty target returns all-``inf`` and does not
    raise: an empty simulated network is the legitimate high end of a bracket,
    and rejecting an empty observed network is the caller's decision.
    """
    graph = metric.graph
    active = graph.active
    n_cells = int(active.size)
    target = np.asarray(target_mask, dtype=bool).reshape(-1)
    if target.size != n_cells:
        raise ValueError(f"target_mask must have {n_cells} entries, got {target.size}.")

    distance = np.full(n_cells, np.inf, dtype="float64")
    distance[~active] = np.nan
    is_target = target & active
    distance[is_target] = 0.0

    downstream = graph.downstream
    edge_length = metric.edge_length
    # Ascending elevation: every receiver is finalized before its own donors,
    # so a single pass is enough and an infinite distance propagates on its own.
    for cell_id in graph.order[::-1].tolist():
        if is_target[cell_id]:
            continue
        receiver = int(downstream[cell_id])
        if receiver < 0:
            continue
        distance[cell_id] = edge_length[cell_id] + distance[receiver]
    return distance


def mean_downslope_distance(
    distance: Any,
    support_mask: Any,
    *,
    weights: Any | None = None,
    saturation_cap_m: float | None = None,
) -> DownslopeDistanceSummary:
    """Weighted mean of a distance field over a support, with infinite capping.

    ``weights`` defaults to one per cell, which is the unweighted average of the
    paper; pass the cell areas to weight by area instead. Unreachable cells are
    replaced by ``saturation_cap_m`` when it is given. Without a cap they keep
    their infinite value and the mean is infinite: they are never dropped, since
    an excluded set that moves with the calibrated parameter makes two trials
    incomparable.
    """
    values = np.asarray(distance, dtype=float).reshape(-1)
    support = np.asarray(support_mask, dtype=bool).reshape(-1)
    if support.size != values.size:
        raise ValueError(f"support_mask must have {values.size} entries, got {support.size}.")

    undefined = support & np.isnan(values)
    unreachable = support & np.isinf(values)
    reached = support & np.isfinite(values)
    scored = reached | unreachable

    capped = values
    if saturation_cap_m is not None:
        cap = float(saturation_cap_m)
        if not np.isfinite(cap) or cap < 0.0:
            raise ValueError(f"saturation_cap_m must be finite and positive, got {cap}.")
        capped = np.where(unreachable, cap, values)

    if not np.any(scored):
        mean_m = float("nan")
        max_m = float("nan")
    else:
        scored_values = capped[scored]
        if weights is None:
            scored_weights = np.ones(scored_values.size, dtype="float64")
        else:
            all_weights = np.asarray(weights, dtype=float).reshape(-1)
            if all_weights.size != values.size:
                raise ValueError(
                    f"weights must have {values.size} entries, got {all_weights.size}."
                )
            scored_weights = all_weights[scored]
            if not np.all(np.isfinite(scored_weights)) or np.any(scored_weights <= 0.0):
                raise ValueError(
                    "weights must be finite and strictly positive over the support; a zero "
                    "weight on an unreachable cell would silently return NaN."
                )
        mean_m = float(np.average(scored_values, weights=scored_weights))
        max_m = float(scored_values.max())

    return DownslopeDistanceSummary(
        mean_m=mean_m,
        max_m=max_m,
        n_support=int(support.sum()),
        n_reached=int(reached.sum()),
        n_unreachable=int(unreachable.sum()),
        n_undefined=int(undefined.sum()),
    )


def longest_descent_length(metric: DownslopeMetric, outlet_mask: Any) -> float:
    """Longest finite descent to the outlet: the catchment saturation cap.

    It is a real length of the catchment, it majors every finite distance, and
    it is static, so substituting it for an unreachable path is conservative and
    does not drift between trials.
    """
    distance = downslope_distance_to_mask(metric, outlet_mask)
    finite = np.isfinite(distance)
    if not np.any(finite):
        raise ValueError(
            "no cell descends to the outlet mask: it is empty, or none of its cells is active."
        )
    return float(distance[finite].max())


__all__ = [
    "DownslopeDistanceSummary",
    "DownslopeMetric",
    "build_downslope_metric",
    "downslope_distance_to_mask",
    "longest_descent_length",
    "mean_downslope_distance",
]
