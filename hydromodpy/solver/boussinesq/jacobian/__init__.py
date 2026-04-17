"""Jacobian builders and sparse operator helpers for the Boussinesq solver."""

from hydromodpy.solver.boussinesq.jacobian.fd import (
    build_colored_sparse_fd_jacobian_triplets,
    build_dense_fd_jacobian,
    build_cell_coupling_rows_by_column,
    build_sparse_fd_jacobian_triplets,
    color_columns_by_row_overlap,
)
from hydromodpy.solver.boussinesq.jacobian.semianalytic import (
    build_sparse_semianalytic_base_jacobian_triplets,
    build_sparse_semianalytic_regularized_partition_jacobian_triplets,
)

__all__ = [
    "build_dense_fd_jacobian",
    "build_cell_coupling_rows_by_column",
    "build_colored_sparse_fd_jacobian_triplets",
    "build_sparse_fd_jacobian_triplets",
    "build_sparse_semianalytic_base_jacobian_triplets",
    "build_sparse_semianalytic_regularized_partition_jacobian_triplets",
    "color_columns_by_row_overlap",
]
