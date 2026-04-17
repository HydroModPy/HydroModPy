"""Regularized-partition saturation triplets for the Boussinesq Jacobian."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    accumulate_internal_flux_residual,
    boundary_head_edge_flux_from_head,
    internal_edge_flux_from_head,
    resolve_boundary_head_inputs,
)
from hydromodpy.solver.boussinesq.jacobian_common import (
    as_cell_vector,
    concatenate_triplets,
    saturated_thickness_derivative_from_head,
)
from hydromodpy.solver.boussinesq.jacobian_operator_triplets import (
    build_sparse_semianalytic_triplets,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def build_sparse_semianalytic_partition_saturation_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    regularization_radius: float,
    surface_input_rate_m_s: np.ndarray | float | None,
    boundary_head_m_by_edge: np.ndarray | None,
    prescribed_head_m_by_cell: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Differentiate the regularized-partition saturation contribution."""
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
    lateral_triplets = build_sparse_semianalytic_triplets(
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
        as_cell_vector(surface_input_rate_m_s, n_cells=n_cells),
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

    return concatenate_triplets(
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


__all__ = ["build_sparse_semianalytic_partition_saturation_triplets"]
