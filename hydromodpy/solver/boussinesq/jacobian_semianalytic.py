"""Semi-analytic Jacobian helpers for the Boussinesq residual.

The current implementation targets the pragmatic middle ground discussed during
the sparse-runtime refactor:

- storage, internal fluxes, imposed-head exchanges and drainage are
  differentiated analytically, using the exact formulas already present in the
  assembly code;
- the saturation-excess term remains outside this module and can still be
  handled by colored finite differences because it mixes a smooth exponential
  factor with piecewise `max/clip` operators.

This keeps the difficult non-smooth part isolated while removing most of the
finite-difference burden from the Jacobian build.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

_MIN_DISTANCE_M = 1.0e-12


def saturated_thickness_derivative_from_head(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> np.ndarray:
    """Return the piecewise derivative of saturated thickness with respect to head."""
    head = np.asarray(head_m, dtype=float)
    max_thickness = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    raw_thickness = head - mesh.z_bottom_m
    active = (raw_thickness > 0.0) & (raw_thickness < max_thickness)
    return active.astype(float, copy=False)


def build_sparse_semianalytic_base_jacobian_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    dt_seconds: float | None = None,
    imposed_head_m_by_edge: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build the sparse Jacobian triplets for the smooth residual blocks.

    Included terms:

    - transient storage term when ``dt_seconds`` is provided,
    - internal edge flux residual,
    - imposed-head edge exchanges,
    - drainage leakage.

    Excluded terms:

    - recharge and wells, which are head-independent in the current backend,
    - saturation excess, which is intentionally left to a separate correction
      path because of its mixed smooth / piecewise character.
    """
    head = np.asarray(head_m, dtype=float).reshape(-1)
    n_cells = int(mesh.n_cells)
    if head.size != n_cells:
        raise ValueError(
            f"head_m length must match mesh.n_cells ({head.size} != {n_cells})."
        )

    data_parts: list[np.ndarray] = []
    row_parts: list[np.ndarray] = []
    col_parts: list[np.ndarray] = []

    def _append_diagonal(values: np.ndarray) -> None:
        diag_values = np.asarray(values, dtype=float).reshape(-1)
        if diag_values.size != n_cells:
            raise ValueError("Diagonal contribution length must match mesh.n_cells.")
        active = np.flatnonzero(diag_values != 0.0).astype(int, copy=False)
        if active.size == 0:
            return
        data_parts.append(diag_values[active].astype(float, copy=False))
        row_parts.append(active)
        col_parts.append(active.copy())

    if dt_seconds is not None:
        dt = float(dt_seconds)
        if dt <= 0.0:
            raise ValueError("dt_seconds must be strictly positive when provided.")
        storage_diag = mesh.cell_area_m2 * mesh.storage_coefficient / dt
        _append_diagonal(storage_diag)

    db_dh = saturated_thickness_derivative_from_head(mesh, head)
    _append_internal_flux_triplets(
        mesh,
        head,
        db_dh,
        data_parts=data_parts,
        row_parts=row_parts,
        col_parts=col_parts,
    )
    _append_imposed_head_triplets(
        mesh,
        head,
        db_dh,
        imposed_head_m_by_edge=imposed_head_m_by_edge,
        data_parts=data_parts,
        row_parts=row_parts,
        col_parts=col_parts,
    )
    drainage_diag = _drainage_diagonal_derivative(
        mesh,
        head,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    _append_diagonal(drainage_diag)

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


def _append_internal_flux_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    db_dh: np.ndarray,
    *,
    data_parts: list[np.ndarray],
    row_parts: list[np.ndarray],
    col_parts: list[np.ndarray],
) -> None:
    data: list[float] = []
    rows: list[int] = []
    cols: list[int] = []
    head = np.asarray(head_m, dtype=float)
    for edge_index in range(mesh.n_edges):
        cell_a = int(mesh.edge_cell_a[edge_index])
        cell_b = int(mesh.edge_cell_b[edge_index])
        if cell_b < 0:
            continue
        conductivity_edge = _harmonic_conductivity(
            float(mesh.hydraulic_conductivity_m_s[cell_a]),
            float(mesh.hydraulic_conductivity_m_s[cell_b]),
        )
        if conductivity_edge <= 0.0:
            continue
        distance_m = max(float(mesh.edge_distance_m[edge_index]), _MIN_DISTANCE_M)
        edge_scale = (
            conductivity_edge * float(mesh.edge_length_m[edge_index]) / distance_m
        )
        thickness_edge = 0.5 * (
            float(_saturated_thickness_value(mesh, head, cell_a))
            + float(_saturated_thickness_value(mesh, head, cell_b))
        )
        tau = edge_scale * thickness_edge
        delta_h = float(head[cell_b] - head[cell_a])
        d_tau_d_ha = 0.5 * edge_scale * float(db_dh[cell_a])
        d_tau_d_hb = 0.5 * edge_scale * float(db_dh[cell_b])
        d_flux_d_ha = tau - d_tau_d_ha * delta_h
        d_flux_d_hb = -tau - d_tau_d_hb * delta_h

        data.extend([d_flux_d_ha, d_flux_d_hb, -d_flux_d_ha, -d_flux_d_hb])
        rows.extend([cell_a, cell_a, cell_b, cell_b])
        cols.extend([cell_a, cell_b, cell_a, cell_b])

    if data:
        data_parts.append(np.asarray(data, dtype=float))
        row_parts.append(np.asarray(rows, dtype=int))
        col_parts.append(np.asarray(cols, dtype=int))


def _append_imposed_head_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    db_dh: np.ndarray,
    *,
    imposed_head_m_by_edge: np.ndarray | None,
    data_parts: list[np.ndarray],
    row_parts: list[np.ndarray],
    col_parts: list[np.ndarray],
) -> None:
    imposed_heads = _as_edge_vector(
        imposed_head_m_by_edge,
        n_edges=mesh.n_edges,
    )
    head = np.asarray(head_m, dtype=float)
    data: list[float] = []
    rows: list[int] = []
    cols: list[int] = []
    for edge_index in range(mesh.n_edges):
        imposed_head = float(imposed_heads[edge_index])
        if not np.isfinite(imposed_head):
            continue
        edge_length = float(mesh.edge_length_m[edge_index])

        cell_a = int(mesh.edge_cell_a[edge_index])
        distance_a = max(
            float(mesh.edge_midpoint_distance_to_cell_a_m[edge_index]),
            _MIN_DISTANCE_M,
        )
        coeff_a = (
            max(float(mesh.hydraulic_conductivity_m_s[cell_a]), 0.0)
            * edge_length
            / distance_a
        )
        thickness_a = float(_saturated_thickness_value(mesh, head, cell_a))
        tau_a = coeff_a * thickness_a
        d_tau_a = coeff_a * float(db_dh[cell_a])
        derivative_a = tau_a - d_tau_a * (imposed_head - float(head[cell_a]))
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
            max(float(mesh.hydraulic_conductivity_m_s[cell_b]), 0.0)
            * edge_length
            / distance_b
        )
        thickness_b = float(_saturated_thickness_value(mesh, head, cell_b))
        tau_b = coeff_b * thickness_b
        if tau_b <= 0.0 and db_dh[cell_b] == 0.0:
            continue
        d_tau_b = coeff_b * float(db_dh[cell_b])
        derivative_b = tau_b - d_tau_b * (imposed_head - float(head[cell_b]))
        data.append(derivative_b)
        rows.append(cell_b)
        cols.append(cell_b)

    if data:
        data_parts.append(np.asarray(data, dtype=float))
        row_parts.append(np.asarray(rows, dtype=int))
        col_parts.append(np.asarray(cols, dtype=int))


def _drainage_diagonal_derivative(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> np.ndarray:
    if drainage_conductance_m2_s is None:
        return np.zeros(mesh.n_cells, dtype=float)
    conductance = _as_cell_vector(
        drainage_conductance_m2_s,
        n_cells=mesh.n_cells,
    )
    auto_conductance = mesh.hydraulic_conductivity_m_s * mesh.cell_area_m2
    effective_conductance = np.where(conductance > 0.0, conductance, auto_conductance)
    head = np.asarray(head_m, dtype=float)
    active = head > mesh.z_top_m
    return np.where(active, effective_conductance, 0.0).astype(float, copy=False)


def _saturated_thickness_value(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    cell_index: int,
) -> float:
    max_thickness = max(
        float(mesh.z_top_m[cell_index] - mesh.z_bottom_m[cell_index]),
        0.0,
    )
    raw = float(np.asarray(head_m, dtype=float)[cell_index] - mesh.z_bottom_m[cell_index])
    return float(np.clip(raw, 0.0, max_thickness))


def _harmonic_conductivity(
    conductivity_a_m_s: float,
    conductivity_b_m_s: float,
) -> float:
    if conductivity_a_m_s <= 0.0 or conductivity_b_m_s <= 0.0:
        return 0.0
    return 2.0 / ((1.0 / conductivity_a_m_s) + (1.0 / conductivity_b_m_s))


def _as_cell_vector(
    values: np.ndarray | float | None,
    *,
    n_cells: int,
) -> np.ndarray:
    if values is None:
        return np.zeros(n_cells, dtype=float)
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0:
        return np.zeros(n_cells, dtype=float)
    if array.size == 1:
        return np.full(n_cells, float(array[0]), dtype=float)
    if array.size != int(n_cells):
        raise ValueError(
            f"Expected scalar or vector of length {int(n_cells)}; got {int(array.size)}."
        )
    return array.astype(float, copy=False)


def _as_edge_vector(
    values: np.ndarray | None,
    *,
    n_edges: int,
) -> np.ndarray:
    if values is None:
        return np.full(n_edges, np.nan, dtype=float)
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size != int(n_edges):
        raise ValueError(
            f"Expected vector of length {int(n_edges)}; got {int(array.size)}."
        )
    return array.astype(float, copy=False)


__all__ = [
    "build_sparse_semianalytic_base_jacobian_triplets",
    "saturated_thickness_derivative_from_head",
]
