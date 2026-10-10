"""Regularized-partition saturation triplets for the Boussinesq Jacobian."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    accumulate_internal_flux_residual,
    boundary_head_edge_flux_from_head,
    internal_edge_flux_from_head,
    resolve_boundary_head_inputs,
)
from hydromodpy.solver.boussinesq.assembly.surface import partition_release_share
from hydromodpy.solver.boussinesq.jacobian.common import (
    as_cell_vector,
    concatenate_triplets,
)
from hydromodpy.solver.boussinesq.jacobian.operator_triplets import (
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
    """Differentiate the regularized-partition saturation contribution.

    ``surface_input_rate_m_s`` is the recharge plus the wells per unit area,
    signed, as ``partition_vertical_supply_rate_m_s`` returns it.
    ``regularization_radius`` is a depth in metres.
    """
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
    lateral_flux_residual = np.asarray(internal_flux_residual, dtype=float) + np.asarray(
        boundary_head_flux_residual, dtype=float
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

    surface_input = as_cell_vector(surface_input_rate_m_s, n_cells=n_cells)
    balance_rate = (
        np.divide(
            -lateral_flux_residual,
            mesh.cell_area_m2,
            out=np.zeros(n_cells, dtype=float),
            where=np.asarray(mesh.cell_area_m2, dtype=float) > 0.0,
        )
        + surface_input
    )
    active_ramp = balance_rate > 0.0
    if np.any(prescribed_mask):
        active_ramp = active_ramp & ~prescribed_mask
    ramp_rate = np.where(active_ramp, balance_rate, 0.0)

    regularization, dregularization_dh = partition_release_share(
        mesh,
        head,
        regularization_radius=float(regularization_radius),
    )
    local_diagonal = mesh.cell_area_m2 * ramp_rate * dregularization_dh

    row_scaling = -regularization * active_ramp.astype(float, copy=False)
    lateral_data, lateral_rows, lateral_cols = lateral_triplets
    scaled_lateral_data = (
        np.asarray(lateral_data, dtype=float) * row_scaling[np.asarray(lateral_rows, dtype=int)]
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
