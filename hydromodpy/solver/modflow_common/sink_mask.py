"""Closed depressions of the solver mesh top, the support ``sink_fill`` acts on.

A closed depression has no outlet: water reaching it stagnates and ponds, it
does not seep into a stream. A drain placed there invents a discharge point,
and on a real catchment that is where the drains fire: on the Nancon mesh
(60 395 cells at 50 m) 5.0 % of the cells sit in a depression and 87.6 % of the
simulated seepage cells are among them.

The mask is measured on the surface the model actually solves on, not on the
raw DEM the geographic step read. A raster conditioned on its own grid grows
new pits once it is resampled onto a mesh with a different neighbourhood, so
the only support that answers the question the drain package asks is the mesh
top itself. Nothing is written to disk and nothing is moved: the topography the
solver receives is untouched, only the drain conductance changes.

**The neighbourhood is the four shared faces, and the count depends on it.**
Same top, same flood, same seed, only the graph changes::

    rook  (4 shared faces, what MODFLOW connects)   2 753 cells   4.56 %
    queen (8 neighbours, the D8 convention)         1 280 cells   2.12 %

A factor of 2.15, which is the whole gap with the 2.30 % a raster fill reports
on the same DEM: a raster fill routes in D8, hence queen. Rook is the right
answer to THIS question. A structured MODFLOW grid connects four faces, so a
cell whose only lower neighbour lies on a diagonal genuinely cannot pass its
water on. The split by support rules out clipping as the cause: 5.14 % inside
the catchment against 4.12 % in the buffer.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.depression_filling import fill_depressions_on_graph
from hydromodpy.core.field_routing import (
    cell_adjacency_from_face_connectivity,
    domain_edge_cells,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

__all__ = ("closed_depression_mask", "resolve_sink_mask")


def closed_depression_mask(solver_mesh: SolverMesh) -> np.ndarray:
    """Return the cells of the mesh top no descent leaves the domain from.

    A priority flood seeded on every cell water can leave the mesh through
    raises the closed depressions and nothing else. Inactive cells carry a
    non-finite elevation, so the flood neither crosses them nor raises them:
    the boundary of the active region is the escape.

    Parameters
    ----------
    solver_mesh
        The mesh the flow model is built on. Its top is the surface flooded and
        its planar connectivity is the graph the flood walks.

    Returns
    -------
    ndarray
        ``(n_cells,)`` boolean, True inside a closed depression.

    Raises
    ------
    ValueError
        When the mesh carries no active cell, or no cell water can leave
        through, so the flood would raise the whole surface.
    """
    connectivity = _rectangular_connectivity(solver_mesh)
    top = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    active = ~np.asarray(solver_mesh.inactive_mask[0], dtype=bool).reshape(-1)
    surface = np.where(active & np.isfinite(top), top, np.nan)
    finite = np.isfinite(surface)
    if not finite.any():
        raise ValueError(
            "sink_fill: the solver mesh top carries no active cell with a finite "
            "elevation, so its closed depressions cannot be measured."
        )

    seeds = domain_edge_cells(connectivity, finite)
    if not seeds.any():
        raise ValueError(
            "sink_fill: no cell of the solver mesh holds a boundary edge, so water "
            "cannot leave the domain and a priority flood would raise every cell."
        )

    adjacency = cell_adjacency_from_face_connectivity(connectivity, n_cells=int(surface.size))
    # No epsilon, and a strict test. The increment exists so a filled floor keeps
    # descending for a later walk down the graph; nothing walks this surface, only
    # the mask is read. Kept, it lifts every cell that merely TIES its rim by one
    # epsilon and reports flat ground as a depression: measured on the Nancon mesh,
    # 270 of 3 023 flagged cells were ties with no basin at all, median 1.9 mm.
    report = fill_depressions_on_graph(surface, adjacency, seeds, epsilon=0.0)
    return finite & (report.surface > surface)


def resolve_sink_mask(
    solver_mesh: SolverMesh,
    *,
    sink_fill: bool,
    model_name: str,
) -> np.ndarray | None:
    """Return the sink mask this model must use, or ``None`` when off.

    Called once per model, right after the mesh is built. A failure is raised
    with the model named, because a silently missing mask would leave every
    drain of a depression discharging as if the option had never been set.
    """
    if not sink_fill:
        return None
    try:
        return closed_depression_mask(solver_mesh)
    except ValueError as exc:
        raise ValueError(f"model {model_name!r}: {exc}") from exc


def _rectangular_connectivity(solver_mesh: SolverMesh) -> np.ndarray:
    """Return the planar face-node connectivity as one ``(n_cells, k)`` array.

    A ragged polygon block is padded with -1, the missing-node marker both mesh
    graph builders already skip.
    """
    connectivity = solver_mesh.planar_mesh.flat_connectivity
    if isinstance(connectivity, np.ndarray) and connectivity.ndim == 2:
        return connectivity.astype(np.int64, copy=False)
    rows = [np.asarray(row, dtype=np.int64).reshape(-1) for row in connectivity]
    width = max((row.size for row in rows), default=0)
    padded = np.full((len(rows), width), -1, dtype=np.int64)
    for index, row in enumerate(rows):
        padded[index, : row.size] = row
    return padded
