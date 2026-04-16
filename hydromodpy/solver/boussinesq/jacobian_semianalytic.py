"""Semi-analytic Jacobian helpers for the Boussinesq residual.

The goal of this module is to keep the Jacobian as analytic as possible while
preserving the current piecewise physical closures:

- storage, internal fluxes, boundary-head exchanges and drainage are
  differentiated analytically;
- the regularized-partition saturation-excess term is also differentiated
  analytically almost everywhere, using the exact piecewise derivatives of the
  current ``clip`` / ``max``-based closure.

The remaining non-smoothness is therefore limited to the physical activation
thresholds already present in the residual itself.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    accumulate_internal_flux_residual,
    boundary_head_edge_flux_from_head,
    internal_edge_flux_from_head,
    resolve_boundary_head_inputs,
)
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


def _build_sparse_semianalytic_base_jacobian_triplets_generic(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    dt_seconds: float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build the sparse Jacobian triplets for the base residual blocks.

    Included terms:

    - transient storage term when ``dt_seconds`` is provided,
    - internal edge flux residual,
    - drainage leakage,
    - identity rows for prescribed head cells.

    Excluded terms:

    - recharge and wells, which are head-independent in the current backend,
    - regularized-partition saturation excess, which is assembled separately so
      the same base Jacobian can also serve the mixed complementarity runtime.
    """
    return _build_sparse_semianalytic_triplets(
        mesh,
        head_m,
        dt_seconds=dt_seconds,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        include_storage=True,
        include_internal_flux=True,
        include_boundary_head_flux=True,
        include_drainage=True,
        include_prescribed_identity=True,
    )


def build_sparse_semianalytic_base_jacobian_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    dt_seconds: float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build base Jacobian triplets on the canonical prescribed-cell path."""
    return _build_sparse_semianalytic_base_jacobian_triplets_generic(
        mesh,
        head_m,
        dt_seconds=dt_seconds,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )


def _build_sparse_semianalytic_regularized_partition_jacobian_triplets_generic(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    regularization_radius: float,
    surface_input_rate_m_s: np.ndarray | float | None,
    dt_seconds: float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build the full head-only Jacobian for the regularized-partition model.

    This augments the base residual Jacobian with the derivative of the
    saturation-excess contribution

    ``A q_ex(h) = A G_r(theta(h)) max(balance(h), 0)``.
    """
    base_triplets = _build_sparse_semianalytic_base_jacobian_triplets_generic(
        mesh,
        head_m,
        dt_seconds=dt_seconds,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    saturation_triplets = _build_sparse_semianalytic_partition_saturation_triplets(
        mesh,
        head_m,
        regularization_radius=regularization_radius,
        surface_input_rate_m_s=surface_input_rate_m_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    return _concatenate_triplets(base_triplets, saturation_triplets)


def build_sparse_semianalytic_regularized_partition_jacobian_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    regularization_radius: float,
    surface_input_rate_m_s: np.ndarray | float | None,
    dt_seconds: float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build the full head-only Jacobian on the canonical prescribed-cell path."""
    return _build_sparse_semianalytic_regularized_partition_jacobian_triplets_generic(
        mesh,
        head_m,
        regularization_radius=regularization_radius,
        surface_input_rate_m_s=surface_input_rate_m_s,
        dt_seconds=dt_seconds,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )


def _build_dense_semianalytic_regularized_partition_jacobian_generic(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    regularization_radius: float,
    surface_input_rate_m_s: np.ndarray | float | None,
    dt_seconds: float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> np.ndarray:
    """Build the dense regularized-partition Jacobian from sparse triplets."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    data, row_indices, col_indices = (
        _build_sparse_semianalytic_regularized_partition_jacobian_triplets_generic(
            mesh,
            head,
            dt_seconds=dt_seconds,
            regularization_radius=regularization_radius,
            surface_input_rate_m_s=surface_input_rate_m_s,
            boundary_head_m_by_edge=boundary_head_m_by_edge,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
        )
    )
    jacobian = np.zeros((head.size, head.size), dtype=float)
    if data.size != 0:
        np.add.at(jacobian, (row_indices, col_indices), data)
    return jacobian


def build_dense_semianalytic_regularized_partition_jacobian(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    regularization_radius: float,
    surface_input_rate_m_s: np.ndarray | float | None,
    dt_seconds: float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> np.ndarray:
    """Build the dense regularized-partition Jacobian on the canonical path."""
    return _build_dense_semianalytic_regularized_partition_jacobian_generic(
        mesh,
        head_m,
        regularization_radius=regularization_radius,
        surface_input_rate_m_s=surface_input_rate_m_s,
        dt_seconds=dt_seconds,
        boundary_head_m_by_edge=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )


def _build_sparse_semianalytic_triplets(
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
        raise ValueError(
            f"head_m length must match mesh.n_cells ({head.size} != {n_cells})."
        )

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
        _append_internal_flux_triplets(
            mesh,
            head,
            db_dh,
            prescribed_mask=prescribed_mask,
            data_parts=data_parts,
            row_parts=row_parts,
            col_parts=col_parts,
        )
    if include_boundary_head_flux and np.any(np.isfinite(boundary_head)):
        _append_boundary_head_triplets(
            mesh,
            head,
            db_dh,
            boundary_head_m_by_edge=boundary_head,
            data_parts=data_parts,
            row_parts=row_parts,
            col_parts=col_parts,
        )
    if include_drainage:
        drainage_diag = _drainage_diagonal_derivative(
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


def _build_sparse_semianalytic_partition_saturation_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    regularization_radius: float,
    surface_input_rate_m_s: np.ndarray | float | None,
    boundary_head_m_by_edge: np.ndarray | None,
    prescribed_head_m_by_cell: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Differentiate the regularized-partition saturation contribution.

    The residual contribution is ``A q_ex`` with

    ``q_ex = G_r(theta(h)) max(balance(h), 0)``

    where ``balance`` depends on the lateral residual only. The resulting
    Jacobian splits into:

    - one lateral block scaled row-wise by the active overflow multiplier,
    - one diagonal term from the local derivative of ``G_r(theta(h))``.
    """
    if float(regularization_radius) <= 0.0:
        raise ValueError("regularization_radius must be strictly positive.")

    head = np.asarray(head_m, dtype=float).reshape(-1)
    n_cells = int(mesh.n_cells)
    if head.size != n_cells:
        raise ValueError(
            f"head_m length must match mesh.n_cells ({head.size} != {n_cells})."
        )

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

    internal_edge_flux = internal_edge_flux_from_head(mesh, head)
    internal_flux_residual = accumulate_internal_flux_residual(mesh, internal_edge_flux)
    if np.any(np.isfinite(boundary_head)):
        _, boundary_head_flux_residual = boundary_head_edge_flux_from_head(
            mesh,
            head,
            boundary_head_m_by_edge=boundary_head,
        )
    else:
        boundary_head_flux_residual = np.zeros(n_cells, dtype=float)
    lateral_flux_residual = (
        np.asarray(internal_flux_residual, dtype=float)
        + np.asarray(boundary_head_flux_residual, dtype=float)
    )
    lateral_triplets = _build_sparse_semianalytic_triplets(
        mesh,
        head,
        dt_seconds=None,
        boundary_head_m_by_edge=boundary_head if np.any(np.isfinite(boundary_head)) else None,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=None,
        include_storage=False,
        include_internal_flux=True,
        include_boundary_head_flux=True,
        include_drainage=False,
        include_prescribed_identity=False,
    )

    surface_input = np.maximum(
        _as_cell_vector(surface_input_rate_m_s, n_cells=n_cells),
        0.0,
    )
    balance_rate = np.divide(
        -lateral_flux_residual,
        mesh.cell_area_m2,
        out=np.zeros(n_cells, dtype=float),
        where=np.asarray(mesh.cell_area_m2, dtype=float) > 0.0,
    ) + surface_input
    active_ramp = balance_rate > 0.0
    ramp_rate = np.where(active_ramp, balance_rate, 0.0)

    max_thickness = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    db_dh = saturated_thickness_derivative_from_head(mesh, head)
    thickness = np.clip(head - mesh.z_bottom_m, 0.0, max_thickness)
    saturation_ratio = np.divide(
        thickness,
        max_thickness,
        out=np.zeros(n_cells, dtype=float),
        where=max_thickness > 0.0,
    )
    regularization = np.exp(
        -(1.0 - np.clip(saturation_ratio, 0.0, 1.0)) / float(regularization_radius)
    )
    dtheta_dh = np.divide(
        db_dh,
        max_thickness,
        out=np.zeros(n_cells, dtype=float),
        where=max_thickness > 0.0,
    )
    dregularization_dh = regularization * dtheta_dh / float(regularization_radius)
    local_diagonal = mesh.cell_area_m2 * ramp_rate * dregularization_dh
    if np.any(prescribed_mask):
        local_diagonal = local_diagonal.copy()
        local_diagonal[prescribed_mask] = 0.0

    row_scaling = -regularization * active_ramp.astype(float, copy=False)
    lateral_data, lateral_rows, lateral_cols = lateral_triplets
    scaled_lateral_data = (
        np.asarray(lateral_data, dtype=float)
        * row_scaling[np.asarray(lateral_rows, dtype=int)]
    )
    active_lateral = scaled_lateral_data != 0.0

    diagonal_rows = np.flatnonzero(local_diagonal != 0.0).astype(int, copy=False)
    diagonal_data = local_diagonal[diagonal_rows].astype(float, copy=False)
    diagonal_cols = diagonal_rows.copy()

    return _concatenate_triplets(
        (
            scaled_lateral_data[active_lateral].astype(float, copy=False),
            np.asarray(lateral_rows, dtype=int)[active_lateral],
            np.asarray(lateral_cols, dtype=int)[active_lateral],
        ),
        (
            diagonal_data,
            diagonal_rows,
            diagonal_cols,
        ),
    )


def _append_internal_flux_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    db_dh: np.ndarray,
    *,
    prescribed_mask: np.ndarray,
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


def _append_boundary_head_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    db_dh: np.ndarray,
    *,
    boundary_head_m_by_edge: np.ndarray | None,
    data_parts: list[np.ndarray],
    row_parts: list[np.ndarray],
    col_parts: list[np.ndarray],
) -> None:
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
            max(float(mesh.hydraulic_conductivity_m_s[cell_a]), 0.0)
            * edge_length
            / distance_a
        )
        thickness_a = float(_saturated_thickness_value(mesh, head, cell_a))
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
            max(float(mesh.hydraulic_conductivity_m_s[cell_b]), 0.0)
            * edge_length
            / distance_b
        )
        thickness_b = float(_saturated_thickness_value(mesh, head, cell_b))
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


def _concatenate_triplets(
    *triplet_sets: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data_parts: list[np.ndarray] = []
    row_parts: list[np.ndarray] = []
    col_parts: list[np.ndarray] = []
    for data, row_indices, col_indices in triplet_sets:
        if np.asarray(data).size == 0:
            continue
        data_parts.append(np.asarray(data, dtype=float).reshape(-1))
        row_parts.append(np.asarray(row_indices, dtype=int).reshape(-1))
        col_parts.append(np.asarray(col_indices, dtype=int).reshape(-1))
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


__all__ = [
    "build_sparse_semianalytic_base_jacobian_triplets",
    "build_dense_semianalytic_regularized_partition_jacobian",
    "build_sparse_semianalytic_regularized_partition_jacobian_triplets",
    "saturated_thickness_derivative_from_head",
]
