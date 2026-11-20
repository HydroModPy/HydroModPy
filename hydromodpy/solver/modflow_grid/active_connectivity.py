"""Count the groups of active cells that no flow path joins.

Two active cells are joined when they share a face in one layer, or when they sit one
above the other in the same column with only pass-through cells (``idomain = -1``)
between them. A cell that is not active and not a pass-through (``idomain = 0``) cuts
the column. The cells a lake is connected to are joined too, since the lake stage
couples them: the active cells of its columns, and the active cells that touch its
body (the cells of its columns made inactive) across a face. An active group cut off
from the rest has its heads set by its own boundary conditions alone, and a group
with none of its own is singular. The check warns and never refuses a grid.

It runs on the grid the solver reads, so after the lake footprint is made inactive.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)

_SIZES_SHOWN = 10
"""Number of group sizes the warning lists."""


def active_component_sizes(
    solver_mesh: SolverMesh, lakes: Iterable[Iterable[int]] = ()
) -> np.ndarray:
    """Return the size of each group of connected active cells, largest first.

    A cell is a ``(layer, cell)`` pair. ``lakes`` lists the cells of each lake, whose
    connected cells form one group. The result is empty when no cell is active.
    """
    idomain = np.asarray(solver_mesh.idomain)
    active = idomain > 0
    through = idomain != 0
    nlay, n_cells = active.shape
    geometry = solver_mesh.cell_mesh.geometry
    counts = np.diff(geometry.adjacency_indptr)
    owner_all = np.repeat(np.arange(n_cells, dtype=np.int64), counts)
    neighbour_all = np.asarray(geometry.adjacency_indices, dtype=np.int64)
    once = owner_all < neighbour_all
    owner, neighbour = owner_all[once], neighbour_all[once]

    heads: list[np.ndarray] = []
    tails: list[np.ndarray] = []
    for layer in range(nlay):
        both = active[layer, owner] & active[layer, neighbour]
        heads.append(layer * n_cells + owner[both])
        tails.append(layer * n_cells + neighbour[both])
    for layer in range(nlay - 1):
        both = np.flatnonzero(through[layer] & through[layer + 1])
        heads.append(layer * n_cells + both)
        tails.append((layer + 1) * n_cells + both)

    n_nodes = nlay * n_cells
    n_lakes = 0
    for cells in lakes:
        member = np.zeros(n_cells, dtype=bool)
        member[np.fromiter((int(c) for c in cells), dtype=np.int64)] = True
        reached = active & member
        reached_layers, reached_cells = np.nonzero(reached)
        touching = member[owner_all] & ~member[neighbour_all]
        lake_side, bank = owner_all[touching], neighbour_all[touching]
        bank_layers, bank_pairs = np.nonzero((idomain[:, lake_side] == 0) & active[:, bank])
        node = n_nodes + n_lakes
        for nodes in (
            reached_layers * n_cells + reached_cells,
            bank_layers * n_cells + bank[bank_pairs],
        ):
            heads.append(np.full(nodes.size, node, dtype=np.int64))
            tails.append(nodes)
        n_lakes += 1

    head = np.concatenate(heads)
    tail = np.concatenate(tails)
    size = n_nodes + n_lakes
    graph = coo_matrix((np.ones(head.size, dtype=np.int8), (head, tail)), shape=(size, size))
    _, labels = connected_components(graph, directed=False)
    sizes = np.bincount(labels[:n_nodes][active.reshape(-1)])
    return np.sort(sizes[sizes > 0])[::-1]


def warn_on_disconnected_active_cells(
    solver_mesh: SolverMesh, lakes: Iterable[Iterable[int]] = ()
) -> np.ndarray:
    """Warn when the active cells form more than one group, and return the group sizes."""
    sizes = active_component_sizes(solver_mesh, lakes)
    if sizes.size > 1:
        shown = ", ".join(str(int(size)) for size in sizes[:_SIZES_SHOWN])
        more = "" if sizes.size <= _SIZES_SHOWN else f", and {sizes.size - _SIZES_SHOWN} more"
        logger.warning(
            "The active cells form %d groups that no face, vertical connection or lake "
            "joins, of %s cells%s. A group cut off from the rest takes its heads from its "
            "own boundary conditions only, and one without any is singular; check the "
            "domain mask and the inactive cells.",
            int(sizes.size),
            shown,
            more,
        )
    return sizes


__all__ = ["active_component_sizes", "warn_on_disconnected_active_cells"]
