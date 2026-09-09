"""Route the per-cell aquifer release downstream, to get a discharge anywhere.

``discharge`` on ``support="domain"`` sums the release of the whole catchment and
answers for the outlet alone. A gauge that is not at the outlet closes a smaller
catchment and cannot be compared to that sum, so scoring it needs the discharge
AT ITS OWN CELL.

The quantity routed here is the per-cell release the union of packages already
reports: DRN, the drain flux handed to the mover, SFR, LAK and a stream-role
CHD. That union is what makes this package-agnostic. Every one of those records
is a flux ACROSS THE AQUIFER FACE, counted once where it crosses, so summing
them upstream of a cell is the water that reached the surface network above it,
whatever package carried it. A mover record on a surface package moves water
between surface features and is excluded upstream, in
``excluded_release_records_for_model``, for the same reason.

At the outlet cell the upstream set is the whole catchment and the routed value
is the domain sum, by construction. That identity is the contract: a per-cell
discharge that does not reproduce the domain series at the outlet is wrong, and
:mod:`tests.unit.solver.test_discharge_routing` checks it.

What this does NOT model is the routing the surface network performs on its own:
channel storage, diversions, evaporation from a reach or a lake. It sums what
entered the network upstream. Under SFR, MODFLOW itself routes the water and its
per-reach ``downstream_flow`` is the faithful quantity; this module is what every
backend and every package combination can answer.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.core.field_routing import (
    accumulate_on_downhill_graph,
    build_downhill_graph,
    cell_adjacency_from_face_connectivity,
)
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def _dense_connectivity(planar_mesh: Any) -> np.ndarray:
    """Return the face-node connectivity as a dense integer array."""
    connectivity = planar_mesh.flat_connectivity
    if isinstance(connectivity, np.ndarray) and connectivity.ndim == 2:
        return connectivity.astype(int, copy=False)
    rows = [np.asarray(row, dtype=int).reshape(-1) for row in connectivity]
    width = max(row.size for row in rows)
    dense = np.full((len(rows), width), -1, dtype=int)
    for index, row in enumerate(rows):
        dense[index, : row.size] = row
    return dense


def routing_graph_for_model(model: Any, *, diagonal_neighbors: bool = False):
    """Build the downhill graph the release is routed on, from the mesh top.

    The surface is the model top the solver itself meshed, never the raster the
    geographic step conditioned: sampling that raster at cell centres grows new
    pits and drops the cells whose centre falls on nodata, which the network
    criterion measured as leaving half its support unreachable.
    """
    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is None:
        raise ValueError(
            "a per-cell discharge needs the solver mesh to route on, and this model carries none."
        )
    planar_mesh = solver_mesh.planar_mesh
    connectivity = _dense_connectivity(planar_mesh)
    top = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    vertices = np.asarray(planar_mesh.vertices, dtype=float)
    centroids = np.asarray(solver_mesh.cell_centroids(), dtype=float)

    adjacency = None
    if diagonal_neighbors:
        adjacency = cell_adjacency_from_face_connectivity(connectivity, n_cells=top.size)
    return build_downhill_graph(
        top,
        connectivity,
        vertices=vertices,
        centroids=centroids,
        inactive_mask=~np.isfinite(top),
        adjacency=adjacency,
    )


def route_release_to_discharge(
    release: np.ndarray,
    graph: Any,
    *,
    catchment_mask: np.ndarray,
) -> np.ndarray:
    """Accumulate a per-cell release downstream and return it per cell.

    ``release`` is ``(n_times, n_cells)`` or ``(n_cells,)`` in m3/s per cell, the
    frame ``release_flux`` already serves. ``catchment_mask`` zeroes the cells
    outside the delineated catchment before routing: the mesh is built on a
    buffered box, and the neighbouring basins drain into it. Measured on the
    Nancon at 25 m, the unmasked domain carries 2.4 times the water the gauge
    sees.
    """
    values = np.asarray(release, dtype=float)
    single = values.ndim == 1
    stack = values.reshape(1, -1) if single else values
    mask = np.asarray(catchment_mask, dtype=bool).reshape(-1)
    if mask.size != stack.shape[1]:
        raise ValueError(
            f"the catchment mask holds {mask.size} cells and the release {stack.shape[1]}."
        )
    if not mask.any():
        raise ValueError("the catchment mask of a per-cell discharge holds no cell.")

    inside = np.where(mask[None, :], np.nan_to_num(stack, nan=0.0), 0.0)
    accumulated = accumulate_on_downhill_graph(graph, inside)
    accumulated = np.nan_to_num(accumulated, nan=0.0)
    return accumulated[0] if single else accumulated


def flat_cell_index(model: Any, cell: tuple[int, int, int]) -> int:
    """Return the flat mesh index of a ``(layer, row, col)`` observable cell.

    The release is summed over layers onto one value per planar cell, so the
    layer is dropped here. On an unstructured mesh a cell arrives as
    ``(layer, 0, cell_id)`` and the third slot already IS the flat index, which
    is the convention ``find_cell_at_point`` and the head reader share.
    """
    solver_mesh = model.solver_mesh
    _, row, col = (int(part) for part in cell)
    n_cells = int(solver_mesh.n_cells)
    if not solver_mesh.is_structured:
        if row != 0:
            raise ValueError(
                f"an unstructured mesh addresses a cell as (layer, 0, cell_id); got row={row}."
            )
        index = col
    else:
        index = row * int(solver_mesh.ncol) + col
    if not 0 <= index < n_cells:
        raise ValueError(f"cell {cell} maps to flat index {index}, outside the {n_cells} cells.")
    return index


def upstream_area_m2(model: Any, graph: Any, *, catchment_mask: np.ndarray) -> np.ndarray:
    """Return the catchment area drained by each cell, in m2.

    Accumulating the cell areas on the same graph as the release is what keeps
    the two consistent: the runoff a gauge sees is the runoff over exactly the
    cells whose release it also sees.
    """
    areas = np.asarray(model.solver_mesh.cell_areas(), dtype=float).reshape(-1)
    return route_release_to_discharge(areas, graph, catchment_mask=catchment_mask)


__all__ = [
    "flat_cell_index",
    "route_release_to_discharge",
    "routing_graph_for_model",
    "upstream_area_m2",
]
