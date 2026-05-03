"""Pure-function derivations of secondary fields from primary outputs.

The functions here turn primary fields (head, surface elevation, drain
budget) into the quantities needed by figures and exports - water-table
elevation, depth, seepage masks, fluxes. They never read the catalog
directly: callers pass in numpy or xarray arrays and receive arrays back.

This keeps display code free of physics: a figure asks for a derived field
already computed; the catalog or the extractor is responsible for invoking
these helpers when ingesting solver output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import xarray as xr

if TYPE_CHECKING:
    ArrayLike = np.ndarray | xr.DataArray
else:
    ArrayLike = Any

__all__ = [
    "accumulate_downhill_on_mesh",
    "active_surface_mask",
    "cell_adjacency_from_face_connectivity",
    "cell_centroids_from_mesh",
    "drain_budget_to_positive_outflow",
    "find_drain_budget_key",
    "fluxes_from_budget",
    "seepage_mask",
    "watertable_depth",
    "watertable_elevation",
]

DRAIN_BUDGET_KEYS = ("drn", "drain", "drains", "DRN", "DRAINS")


def watertable_elevation(head: ArrayLike, top: ArrayLike) -> ArrayLike:
    """Water-table elevation - head clipped to the surface elevation.

    ``head`` is an N-D array shaped ``(..., n_cells)`` (or ``(n_layers, n_cells)``
    for multilayer models). ``top`` is a per-cell surface array.
    """
    if _is_data_array(head):
        wt = head.where(head <= top, top)
        wt.attrs.update(units="m", long_name="Water-table elevation")
        return wt
    head_arr = np.asarray(head, dtype=float)
    top_arr = np.asarray(top, dtype=float)
    if head_arr.ndim == 2 and head_arr.shape[1] == top_arr.size:
        # Multilayer: pick uppermost saturated head per cell.
        wt = np.full(head_arr.shape[1], np.nan, dtype=float)
        for layer in range(head_arr.shape[0]):
            mask = np.isfinite(head_arr[layer]) & np.isnan(wt)
            wt[mask] = head_arr[layer, mask]
        return np.minimum(wt, top_arr)
    return np.minimum(head_arr, top_arr)


def watertable_depth(head: ArrayLike, top: ArrayLike) -> ArrayLike:
    """Depth from surface to water table, clipped to ≥ 0."""
    if _is_data_array(head):
        depth = (top - head).where((top - head) >= 0, 0.0)
        depth.attrs.update(units="m", long_name="Depth to water table")
        return depth
    wt = watertable_elevation(head, top)
    top_arr = np.asarray(top, dtype=float)
    return np.maximum(top_arr - wt, 0.0)


def seepage_mask(head: ArrayLike, top: ArrayLike) -> ArrayLike:
    """Boolean cells where the water table reaches or exceeds the surface."""
    if _is_data_array(head):
        return (head >= top).astype("int8")
    wt = watertable_elevation(head, top)
    return (np.asarray(wt) >= np.asarray(top)).astype("int8")


def find_drain_budget_key(mapping: Any) -> str | None:
    """Return the first stored drain-budget key found in a mapping/group."""
    for key in DRAIN_BUDGET_KEYS:
        try:
            if key in mapping:
                return key
        except TypeError:
            return None
    return None


def drain_budget_to_positive_outflow(
    component_field: ArrayLike,
    *,
    n_cells: int | None = None,
) -> np.ndarray:
    """Convert a signed DRN/DRAINS budget field to positive drain outflow.

    MODFLOW cell-budget records conventionally use negative values for water
    leaving the aquifer. Legacy HydroModPy post-processing, active-network
    figures, and transport seepage coupling consume the opposite convention:
    ``outflow_drain >= 0``. This helper makes that sign conversion explicit
    and sums multilayer budgets onto one value per planar cell.

    If the input is already entirely non-negative, it is treated as an
    already-positive outflow field for compatibility with older stores.
    """
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

    finite = np.isfinite(signed) & (signed > -9000.0)
    positive_outflow = np.where(finite, np.maximum(-signed, 0.0), 0.0)
    if (
        np.any(finite)
        and not np.any(positive_outflow[finite] > 0.0)
        and np.any(signed[finite] > 0.0)
        and not np.any(signed[finite] < 0.0)
    ):
        positive_outflow = np.where(finite, signed, 0.0)
    return positive_outflow.sum(axis=0).astype("float64", copy=False)


def active_surface_mask(surface_top: ArrayLike, *, nodata_floor: float = -9000.0) -> np.ndarray:
    """Return True for cells with a finite, non-nodata surface elevation."""
    surface = np.asarray(surface_top, dtype=float).reshape(-1)
    return np.isfinite(surface) & (surface > float(nodata_floor))


def cell_adjacency_from_face_connectivity(
    face_node_connectivity: ArrayLike,
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
    vertices: ArrayLike,
    face_node_connectivity: ArrayLike,
) -> np.ndarray:
    """Return one XY centroid per mesh face."""
    points = np.asarray(vertices, dtype=float)
    connectivity = np.asarray(face_node_connectivity, dtype=int)
    if connectivity.ndim == 1:
        connectivity = connectivity.reshape(1, -1)
    centroids = np.full((connectivity.shape[0], 2), np.nan, dtype="float64")
    for cell_id, row in enumerate(connectivity):
        nodes = np.asarray(row, dtype=int)
        nodes = nodes[(nodes >= 0) & (nodes < points.shape[0])]
        if nodes.size == 0:
            continue
        centroids[cell_id] = np.nanmean(points[nodes, :2], axis=0)
    return centroids


def accumulate_downhill_on_mesh(
    local_values: ArrayLike,
    reference_values: ArrayLike,
    face_node_connectivity: ArrayLike,
    *,
    vertices: ArrayLike | None = None,
    inactive_mask: ArrayLike | None = None,
) -> np.ndarray:
    """Accumulate per-cell source values along the steepest downhill mesh path."""
    local = np.asarray(local_values, dtype=float).reshape(-1)
    reference = np.asarray(reference_values, dtype=float).reshape(-1)
    if local.size != reference.size:
        raise ValueError(
            "local_values and reference_values must have the same number of cells "
            f"({local.size} != {reference.size})."
        )

    n_cells = int(local.size)
    if inactive_mask is None:
        inactive = np.zeros(n_cells, dtype=bool)
    else:
        inactive = np.asarray(inactive_mask, dtype=bool).reshape(-1)
        if inactive.size != n_cells:
            raise ValueError(f"inactive_mask must have {n_cells} entries, got {inactive.size}.")

    active = (~inactive) & np.isfinite(reference)
    if not np.any(active):
        return np.zeros(n_cells, dtype="float64")

    adjacency = cell_adjacency_from_face_connectivity(
        face_node_connectivity,
        n_cells=n_cells,
    )
    centroids = None
    if vertices is not None:
        centroids = cell_centroids_from_mesh(vertices, face_node_connectivity)
        if centroids.shape[0] != n_cells or not np.any(np.isfinite(centroids)):
            centroids = None

    ref_active = reference[active]
    ref_range = float(np.nanmax(ref_active) - np.nanmin(ref_active)) if ref_active.size else 0.0
    tolerance = max(1.0e-9, 1.0e-9 * max(abs(ref_range), 1.0))
    downstream = np.full(n_cells, -1, dtype=int)

    for cell_id in np.flatnonzero(active).tolist():
        best_neighbor = -1
        best_score = 0.0
        cell_ref = float(reference[cell_id])
        for neighbor in adjacency[int(cell_id)]:
            if neighbor < 0 or neighbor >= n_cells or not bool(active[neighbor]):
                continue
            drop = cell_ref - float(reference[int(neighbor)])
            if not np.isfinite(drop) or drop <= tolerance:
                continue
            score = drop
            if centroids is not None and np.all(np.isfinite(centroids[[cell_id, neighbor]])):
                delta = centroids[int(cell_id)] - centroids[int(neighbor)]
                distance = max(float(np.hypot(delta[0], delta[1])), 1.0e-12)
                score = drop / distance
            if score > best_score:
                best_score = float(score)
                best_neighbor = int(neighbor)
        downstream[int(cell_id)] = int(best_neighbor)

    clean_local = np.where(active & np.isfinite(local), np.maximum(local, 0.0), 0.0)
    accumulated = np.zeros(n_cells, dtype="float64")
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


def fluxes_from_budget(
    component_field: ArrayLike,
    cell_area: ArrayLike,
) -> ArrayLike:
    """Convert a per-cell budget flux (m³/d) into a unit flux (m/d).

    Negative values are out-of-aquifer fluxes (e.g. drains); positive values
    are inflow. Cells with zero area pass through as NaN.
    """
    if _is_data_array(component_field):
        area = xr.DataArray(np.asarray(cell_area, dtype=float))
        flux = component_field / area.where(area > 0)
        flux.attrs.update(units="m d-1", long_name="Cell-averaged flux")
        return flux
    field = np.asarray(component_field, dtype=float)
    area = np.asarray(cell_area, dtype=float)
    out = np.full_like(field, np.nan, dtype=float)
    valid = area > 0
    out[..., valid] = field[..., valid] / area[valid]
    return out


def _is_data_array(value: object) -> bool:
    data_array_type = getattr(xr, "DataArray", None)
    if not isinstance(data_array_type, type):
        return False
    return isinstance(value, data_array_type)
