"""Semi-analytic Jacobian helpers for the Boussinesq residual.

This module remains the public façade for semianalytic Jacobian assembly.
Its implementation is now split internally into:

- `jacobian_common.py` for derivative and COO helper utilities,
- `jacobian_operator_triplets.py` for the base residual operators,
- `jacobian_partition_triplets.py` for the regularized-partition saturation term.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.jacobian_common import (
    concatenate_triplets,
    saturated_thickness_derivative_from_head,
)
from hydromodpy.solver.boussinesq.jacobian_operator_triplets import (
    build_sparse_semianalytic_triplets,
)
from hydromodpy.solver.boussinesq.jacobian_partition_triplets import (
    build_sparse_semianalytic_partition_saturation_triplets,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def _build_sparse_semianalytic_base_jacobian_triplets_generic(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    dt_seconds: float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build the sparse Jacobian triplets for the base residual blocks."""
    return build_sparse_semianalytic_triplets(
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
    """Build the full head-only Jacobian for the regularized-partition model."""
    base_triplets = _build_sparse_semianalytic_base_jacobian_triplets_generic(
        mesh,
        head_m,
        dt_seconds=dt_seconds,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    saturation_triplets = build_sparse_semianalytic_partition_saturation_triplets(
        mesh,
        head_m,
        regularization_radius=regularization_radius,
        surface_input_rate_m_s=surface_input_rate_m_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    return concatenate_triplets(base_triplets, saturation_triplets)


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


__all__ = [
    "build_dense_semianalytic_regularized_partition_jacobian",
    "build_sparse_semianalytic_base_jacobian_triplets",
    "build_sparse_semianalytic_regularized_partition_jacobian_triplets",
    "saturated_thickness_derivative_from_head",
]
