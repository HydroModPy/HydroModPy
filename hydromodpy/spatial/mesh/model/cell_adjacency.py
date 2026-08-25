"""Face adjacency for an unstructured planar mesh (cells sharing an edge)."""

from __future__ import annotations

from typing import Any

import numpy as np


def build_planar_cell_adjacency(
    planar_mesh: Any,
    n_cells: int,
    mesh_support: Any = None,
) -> list[set[int]]:
    """Cell-to-cell neighbour sets (shared-edge) for a planar mesh.

    Prefers the runtime edge->cell incidence when it indexes these cells (a
    boundary edge has a negative second cell). That incidence may instead index
    the finer triangulation a Voronoi dual was built from; then some ids overrun
    ``n_cells``. Because roughly half of those overrunning ids still land below
    ``n_cells``, a per-edge bounds check would silently keep the wrong (triangle)
    topology, so the whole incidence is rejected when ANY id is out of range and
    the adjacency is rebuilt from each cell's polygon connectivity instead.
    """
    adjacency: list[set[int]] = [set() for _ in range(n_cells)]

    if mesh_support is not None:
        edge_a = np.asarray(getattr(mesh_support, "edge_cell_a", ()), dtype=int).reshape(-1)
        edge_b = np.asarray(getattr(mesh_support, "edge_cell_b", ()), dtype=int).reshape(-1)
        max_id = max(int(edge_a.max(initial=-1)), int(edge_b.max(initial=-1)))
        if max_id < n_cells:  # the incidence describes THIS mesh, not a finer one
            for cell_a, cell_b in zip(edge_a.tolist(), edge_b.tolist(), strict=False):
                if cell_a < 0 or cell_b < 0:
                    continue
                adjacency[cell_a].add(cell_b)
                adjacency[cell_b].add(cell_a)
            if any(adjacency):
                return adjacency

    flat_connectivity = getattr(planar_mesh, "flat_connectivity", None)
    if flat_connectivity is None:
        return adjacency

    # Per-cell node lists, ragged-safe for any arity (triangles, quads, Voronoi
    # n-gons): two cells that share an edge (an unordered node pair) are neighbours.
    edge_owner: dict[tuple[int, int], int] = {}
    for cell_id, node_ids in enumerate(flat_connectivity):
        if cell_id >= n_cells:
            break
        nodes = np.asarray(node_ids, dtype=int).reshape(-1)
        arity = int(nodes.size)
        if arity < 3:
            continue
        for node_index in range(arity):
            node_a = int(nodes[node_index])
            node_b = int(nodes[(node_index + 1) % arity])
            edge = (node_a, node_b) if node_a < node_b else (node_b, node_a)
            owner = edge_owner.get(edge)
            if owner is None:
                edge_owner[edge] = cell_id
            elif owner != cell_id:
                adjacency[cell_id].add(owner)
                adjacency[owner].add(cell_id)
    return adjacency
