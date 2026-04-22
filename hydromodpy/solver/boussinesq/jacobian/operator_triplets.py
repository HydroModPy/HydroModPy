"""Base sparse Jacobian triplets for Boussinesq residual operators."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly import resolve_boundary_head_inputs
from hydromodpy.solver.boussinesq.jacobian.common import (
    drainage_diagonal_derivative,
    harmonic_conductivity,
    saturated_thickness_derivative_from_head,
    saturated_thickness_value,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

_MIN_DISTANCE_M = 1.0e-12


def build_sparse_semianalytic_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    dt_seconds: float | None,
    boundary_head_m_by_edge: np.ndarray | None,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    include_storage: bool,
    include_internal_flux: bool,
    include_boundary_head_flux: bool,
    include_drainage: bool,
    include_prescribed_identity: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build one sparse Jacobian subset from selected residual operators."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    n_cells = int(mesh.n_cells)
    if head.size != n_cells:
        raise ValueError(f"head_m length must match mesh.n_cells ({head.size} != {n_cells}).")

    boundary_inputs = resolve_boundary_head_inputs(
        mesh,
        head_m=head,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    head = boundary_inputs.head_m
    boundary_head = boundary_inputs.boundary_head_m_by_edge
    prescribed_mask = boundary_inputs.prescribed_mask
    use_prescribed_cells = bool(np.any(prescribed_mask))

    data_parts: list[np.ndarray] = []
    row_parts: list[np.ndarray] = []
    col_parts: list[np.ndarray] = []

    def _append_diagonal(values: np.ndarray) -> None:
        diag_values = np.asarray(values, dtype=float).reshape(-1)
        if diag_values.size != n_cells:
            raise ValueError("Diagonal contribution length must match mesh.n_cells.")
        if np.any(prescribed_mask):
            diag_values = diag_values.copy()
            diag_values[prescribed_mask] = 0.0
        active = np.flatnonzero(diag_values != 0.0).astype(int, copy=False)
        if active.size == 0:
            return
        data_parts.append(diag_values[active].astype(float, copy=False))
        row_parts.append(active)
        col_parts.append(active.copy())

    if include_storage and dt_seconds is not None:
        dt = float(dt_seconds)
        if dt <= 0.0:
            raise ValueError("dt_seconds must be strictly positive when provided.")
        storage_diag = mesh.cell_area_m2 * mesh.storage_coefficient / dt
        _append_diagonal(storage_diag)

    db_dh = saturated_thickness_derivative_from_head(mesh, head)
    if include_internal_flux:
        append_internal_flux_triplets(
            mesh,
            head,
            db_dh,
            prescribed_mask=prescribed_mask,
            data_parts=data_parts,
            row_parts=row_parts,
            col_parts=col_parts,
        )
    if include_boundary_head_flux and np.any(np.isfinite(boundary_head)):
        append_boundary_head_triplets(
            mesh,
            head,
            db_dh,
            boundary_head_m_by_edge=boundary_head,
            data_parts=data_parts,
            row_parts=row_parts,
            col_parts=col_parts,
        )
    if include_drainage:
        drainage_diag = drainage_diagonal_derivative(
            mesh,
            head,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
        )
        _append_diagonal(drainage_diag)
    if include_prescribed_identity and use_prescribed_cells and np.any(prescribed_mask):
        prescribed_rows = np.flatnonzero(prescribed_mask).astype(int, copy=False)
        data_parts.append(np.ones(prescribed_rows.size, dtype=float))
        row_parts.append(prescribed_rows)
        col_parts.append(prescribed_rows.copy())

    if not data_parts:
        return (
            np.asarray([], dtype=float),
            np.asarray([], dtype=int),
            np.asarray([], dtype=int),
        )
    return (
        np.concatenate(data_parts).astype(float, copy=False),
        np.concatenate(row_parts).astype(int, copy=False),
        np.concatenate(col_parts).astype(int, copy=False),
    )


def append_internal_flux_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    db_dh: np.ndarray,
    *,
    prescribed_mask: np.ndarray,
    data_parts: list[np.ndarray],
    row_parts: list[np.ndarray],
    col_parts: list[np.ndarray],
) -> None:
    """Append the Jacobian contribution of internal inter-cell fluxes."""
    data: list[float] = []
    rows: list[int] = []
    cols: list[int] = []
    head = np.asarray(head_m, dtype=float)
    for edge_index in range(mesh.n_edges):
        cell_a = int(mesh.edge_cell_a[edge_index])
        cell_b = int(mesh.edge_cell_b[edge_index])
        if cell_b < 0:
            continue
        conductivity_edge = harmonic_conductivity(
            float(mesh.hydraulic_conductivity_m_s[cell_a]),
            float(mesh.hydraulic_conductivity_m_s[cell_b]),
        )
        if conductivity_edge <= 0.0:
            continue
        distance_m = max(float(mesh.edge_distance_m[edge_index]), _MIN_DISTANCE_M)
        edge_scale = conductivity_edge * float(mesh.edge_length_m[edge_index]) / distance_m
        thickness_edge = 0.5 * (
            float(saturated_thickness_value(mesh, head, cell_a))
            + float(saturated_thickness_value(mesh, head, cell_b))
        )
        tau = edge_scale * thickness_edge
        delta_h = float(head[cell_b] - head[cell_a])
        d_tau_d_ha = 0.5 * edge_scale * float(db_dh[cell_a])
        d_tau_d_hb = 0.5 * edge_scale * float(db_dh[cell_b])
        d_flux_d_ha = tau - d_tau_d_ha * delta_h
        d_flux_d_hb = -tau - d_tau_d_hb * delta_h

        if not prescribed_mask[cell_a]:
            data.append(d_flux_d_ha)
            rows.append(cell_a)
            cols.append(cell_a)
            if not prescribed_mask[cell_b]:
                data.append(d_flux_d_hb)
                rows.append(cell_a)
                cols.append(cell_b)
        if not prescribed_mask[cell_b]:
            if not prescribed_mask[cell_a]:
                data.append(-d_flux_d_ha)
                rows.append(cell_b)
                cols.append(cell_a)
            data.append(-d_flux_d_hb)
            rows.append(cell_b)
            cols.append(cell_b)

    if data:
        data_parts.append(np.asarray(data, dtype=float))
        row_parts.append(np.asarray(rows, dtype=int))
        col_parts.append(np.asarray(cols, dtype=int))


def append_boundary_head_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    db_dh: np.ndarray,
    *,
    boundary_head_m_by_edge: np.ndarray | None,
    data_parts: list[np.ndarray],
    row_parts: list[np.ndarray],
    col_parts: list[np.ndarray],
) -> None:
    """Append the Jacobian contribution of edge-supported boundary heads."""
    boundary_heads = np.asarray(
        np.full(mesh.n_edges, np.nan, dtype=float)
        if boundary_head_m_by_edge is None
        else boundary_head_m_by_edge,
        dtype=float,
    ).reshape(-1)
    if boundary_heads.size != int(mesh.n_edges):
        raise ValueError(
            f"Expected vector of length {int(mesh.n_edges)}; got {int(boundary_heads.size)}."
        )
    head = np.asarray(head_m, dtype=float)
    data: list[float] = []
    rows: list[int] = []
    cols: list[int] = []
    for edge_index in range(mesh.n_edges):
        boundary_head = float(boundary_heads[edge_index])
        if not np.isfinite(boundary_head):
            continue
        edge_length = float(mesh.edge_length_m[edge_index])

        cell_a = int(mesh.edge_cell_a[edge_index])
        distance_a = max(
            float(mesh.edge_midpoint_distance_to_cell_a_m[edge_index]),
            _MIN_DISTANCE_M,
        )
        coeff_a = (
            max(float(mesh.hydraulic_conductivity_m_s[cell_a]), 0.0) * edge_length / distance_a
        )
        thickness_a = float(saturated_thickness_value(mesh, head, cell_a))
        tau_a = coeff_a * thickness_a
        d_tau_a = coeff_a * float(db_dh[cell_a])
        derivative_a = tau_a - d_tau_a * (boundary_head - float(head[cell_a]))
        data.append(derivative_a)
        rows.append(cell_a)
        cols.append(cell_a)

        cell_b = int(mesh.edge_cell_b[edge_index])
        if cell_b < 0:
            continue
        distance_b = max(
            float(mesh.edge_midpoint_distance_to_cell_b_m[edge_index]),
            _MIN_DISTANCE_M,
        )
        coeff_b = (
            max(float(mesh.hydraulic_conductivity_m_s[cell_b]), 0.0) * edge_length / distance_b
        )
        thickness_b = float(saturated_thickness_value(mesh, head, cell_b))
        tau_b = coeff_b * thickness_b
        if tau_b <= 0.0 and db_dh[cell_b] == 0.0:
            continue
        d_tau_b = coeff_b * float(db_dh[cell_b])
        derivative_b = tau_b - d_tau_b * (boundary_head - float(head[cell_b]))
        data.append(derivative_b)
        rows.append(cell_b)
        cols.append(cell_b)

    if data:
        data_parts.append(np.asarray(data, dtype=float))
        row_parts.append(np.asarray(rows, dtype=int))
        col_parts.append(np.asarray(cols, dtype=int))


__all__ = [
    "append_boundary_head_triplets",
    "append_internal_flux_triplets",
    "build_sparse_semianalytic_triplets",
]
