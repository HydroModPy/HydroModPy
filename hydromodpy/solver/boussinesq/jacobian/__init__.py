"""Jacobian builders and sparse operator helpers for the Boussinesq solver."""

from hydromodpy.solver.boussinesq.jacobian.fd import (
    build_dense_fd_jacobian,
    build_sparse_fd_jacobian_triplets,
    greedy_column_coloring,
)
from hydromodpy.solver.boussinesq.jacobian.semianalytic import (
    build_sparse_semianalytic_base_jacobian_triplets,
    build_sparse_semianalytic_partition_jacobian_triplets,
)

__all__ = [
    "build_dense_fd_jacobian",
    "build_sparse_fd_jacobian_triplets",
    "build_sparse_semianalytic_base_jacobian_triplets",
    "build_sparse_semianalytic_partition_jacobian_triplets",
    "greedy_column_coloring",
]
