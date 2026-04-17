"""Boundary-flux reconstruction helpers for prescribed-head diagnostics.

The Boussinesq driver now treats cell-prescribed heads as the canonical
Dirichlet representation. This module rebuilds the edge-aligned boundary
diagnostic from the canonical prescribed-cell state and the resolved edge
supports used by the driver.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly import boundary_head_edge_flux_from_head
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def rebuild_boundary_edge_flux(
    *,
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    assembly_boundary_edge_flux_m3_s: np.ndarray | None,
    internal_edge_flux_m3_s: np.ndarray | None = None,
    boundary_head_m_by_edge: np.ndarray | None,
    prescribed_head_flux_m3_s: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
) -> np.ndarray:
    """Return the canonical edge-based boundary flux diagnostic.

    When the assembly already carries a non-zero edge diagnostic, this helper
    simply normalizes it. Otherwise, it rebuilds the edge view from the
    prescribed-cell closure and the resolved edge supports supplied by the
    driver.
    """

    current = np.asarray(
        assembly_boundary_edge_flux_m3_s
        if assembly_boundary_edge_flux_m3_s is not None
        else np.zeros(mesh.n_edges, dtype=float),
        dtype=float,
    ).reshape(-1)
    if current.size != int(mesh.n_edges):
        raise ValueError(
            "assembly_boundary_edge_flux_m3_s must have length mesh.n_edges."
        )

    boundary_heads = np.asarray(
        boundary_head_m_by_edge
        if boundary_head_m_by_edge is not None
        else np.full(mesh.n_edges, np.nan, dtype=float),
        dtype=float,
    ).reshape(-1)
    if boundary_heads.size != int(mesh.n_edges):
        raise ValueError("boundary_head_m_by_edge must have length mesh.n_edges.")

    if not np.any(np.isfinite(boundary_heads)):
        return current.copy()

    rebuilt_flux, _ = boundary_head_edge_flux_from_head(
        mesh,
        np.asarray(head_m, dtype=float),
        boundary_head_m_by_edge=boundary_heads,
    )
    rebuilt = np.asarray(rebuilt_flux, dtype=float).copy()
    if np.any(np.abs(current) > 0.0):
        return rebuilt

    prescribed_head = np.asarray(
        prescribed_head_m_by_cell
        if prescribed_head_m_by_cell is not None
        else np.full(mesh.n_cells, np.nan, dtype=float),
        dtype=float,
    ).reshape(-1)
    if prescribed_head.size != int(mesh.n_cells):
        raise ValueError("prescribed_head_m_by_cell must have length mesh.n_cells.")
    prescribed_mask = np.isfinite(prescribed_head)
    if not np.any(prescribed_mask):
        return rebuilt

    internal_flux = np.asarray(
        internal_edge_flux_m3_s
        if internal_edge_flux_m3_s is not None
        else np.zeros(mesh.n_edges, dtype=float),
        dtype=float,
    ).reshape(-1)
    if internal_flux.size != int(mesh.n_edges):
        raise ValueError("internal_edge_flux_m3_s must have length mesh.n_edges.")
    prescribed_flux = np.asarray(
        prescribed_head_flux_m3_s
        if prescribed_head_flux_m3_s is not None
        else np.zeros(mesh.n_cells, dtype=float),
        dtype=float,
    ).reshape(-1)
    if prescribed_flux.size != int(mesh.n_cells):
        raise ValueError("prescribed_head_flux_m3_s must have length mesh.n_cells.")

    active_boundary_support = np.isfinite(boundary_heads) & np.asarray(
        mesh.boundary_edge_mask,
        dtype=bool,
    )
    if not np.any(active_boundary_support):
        return rebuilt

    edge_cell_a = np.asarray(mesh.edge_cell_a, dtype=int)
    edge_cell_b = np.asarray(mesh.edge_cell_b, dtype=int)
    interior_mask = np.asarray(mesh.interior_edge_mask, dtype=bool)
    for cell_index in np.unique(edge_cell_a[active_boundary_support]).tolist():
        cell_index = int(cell_index)
        if not bool(prescribed_mask[cell_index]):
            continue
        supported_boundary_edges = np.flatnonzero(
            active_boundary_support & (edge_cell_a == cell_index)
        ).astype(int, copy=False)
        if supported_boundary_edges.size == 0:
            continue
        outward_exchange = 0.0
        has_free_neighbor = False
        for edge_index in np.flatnonzero(interior_mask).tolist():
            cell_a = int(edge_cell_a[edge_index])
            cell_b = int(edge_cell_b[edge_index])
            flux = float(internal_flux[edge_index])
            if cell_a == cell_index and cell_b >= 0 and not bool(prescribed_mask[cell_b]):
                has_free_neighbor = True
                outward_exchange += flux
            elif cell_b == cell_index and cell_a >= 0 and not bool(prescribed_mask[cell_a]):
                has_free_neighbor = True
                outward_exchange += -flux
        support_flux = (
            -outward_exchange
            if has_free_neighbor
            else float(prescribed_flux[cell_index])
        )
        rebuilt[supported_boundary_edges] = support_flux / float(
            supported_boundary_edges.size
        )
    return rebuilt


__all__ = ["rebuild_boundary_edge_flux"]
