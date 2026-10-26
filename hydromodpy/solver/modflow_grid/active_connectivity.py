"""Count the groups of active cells that no flow path joins.

Two active cells are joined when they share a face in one layer, or when they
sit one above the other in the same column. An active group cut off from the
rest has its heads set by its own boundary conditions alone, and a group with
none of its own is singular. The check warns and never refuses a grid.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)

_SIZES_SHOWN = 10
"""Number of group sizes the warning lists."""


def active_component_sizes(solver_mesh: SolverMesh) -> np.ndarray:
    """Return the size of each group of connected active cells, largest first.

    A cell is a ``(layer, cell)`` pair. The result is empty when no cell is active.
    """
    active = ~np.asarray(solver_mesh.inactive_mask, dtype=bool)
    nlay, n_cells = active.shape
    geometry = solver_mesh.cell_mesh.geometry
    counts = np.diff(geometry.adjacency_indptr)
    owner = np.repeat(np.arange(n_cells, dtype=np.int64), counts)
    neighbour = np.asarray(geometry.adjacency_indices, dtype=np.int64)
    once = owner < neighbour
    owner, neighbour = owner[once], neighbour[once]

    heads: list[np.ndarray] = []
    tails: list[np.ndarray] = []
    for layer in range(nlay):
        both = active[layer, owner] & active[layer, neighbour]
        heads.append(layer * n_cells + owner[both])
        tails.append(layer * n_cells + neighbour[both])
    for layer in range(nlay - 1):
        both = np.flatnonzero(active[layer] & active[layer + 1])
        heads.append(layer * n_cells + both)
        tails.append((layer + 1) * n_cells + both)

    n_nodes = nlay * n_cells
    head = np.concatenate(heads)
    tail = np.concatenate(tails)
    graph = coo_matrix((np.ones(head.size, dtype=np.int8), (head, tail)), shape=(n_nodes, n_nodes))
    _, labels = connected_components(graph, directed=False)
    sizes = np.bincount(labels[active.reshape(-1)])
    return np.sort(sizes[sizes > 0])[::-1]


def warn_on_disconnected_active_cells(solver_mesh: SolverMesh) -> np.ndarray:
    """Warn when the active cells form more than one group, and return the group sizes."""
    sizes = active_component_sizes(solver_mesh)
    if sizes.size > 1:
        shown = ", ".join(str(int(size)) for size in sizes[:_SIZES_SHOWN])
        more = "" if sizes.size <= _SIZES_SHOWN else f", and {sizes.size - _SIZES_SHOWN} more"
        logger.warning(
            "The active cells form %d groups that no face or vertical connection joins, "
            "of %s cells%s. A group cut off from the rest takes its heads from its own "
            "boundary conditions only, and one without any is singular; check the domain "
            "mask and the inactive cells.",
            int(sizes.size),
            shown,
            more,
        )
    return sizes


__all__ = ["active_component_sizes", "warn_on_disconnected_active_cells"]
