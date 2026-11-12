"""The public sparse regularized-partition Jacobian is the dense one, written as triplets.

Heads are in m, the surface input rate in m/s and the residual in m3/s. The mesh is two unit cells,
2 m thick, joined by one edge 1 m long.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.jacobian.semianalytic import (
    build_dense_semianalytic_regularized_partition_jacobian,
    build_sparse_semianalytic_regularized_partition_jacobian_triplets,
)
from tests._helpers.boussinesq_mesh_doubles import _MiniMesh

pytestmark = pytest.mark.fast


def two_cells() -> _MiniMesh:
    return _MiniMesh(
        cell_area_m2=np.ones(2),
        z_top_m=np.full(2, 2.0),
        z_bottom_m=np.zeros(2),
        hydraulic_conductivity_m_s=np.ones(2),
        storage_coefficient=np.full(2, 0.2),
        edge_ids=np.asarray([0]),
        edge_cell_a=np.asarray([0]),
        edge_cell_b=np.asarray([1]),
        edge_length_m=np.ones(1),
        edge_distance_m=np.ones(1),
        edge_midpoint_distance_to_cell_a_m=np.full(1, 0.5),
        edge_midpoint_distance_to_cell_b_m=np.full(1, 0.5),
    )


def test_sparse_triplets_sum_to_the_dense_jacobian() -> None:
    mesh, head = two_cells(), np.array([1.0, 1.5])
    kwargs = dict(regularization_radius=0.25, surface_input_rate_m_s=0.0)

    data, rows, cols = build_sparse_semianalytic_regularized_partition_jacobian_triplets(
        mesh, head, **kwargs
    )
    summed = np.zeros((2, 2))
    np.add.at(summed, (rows, cols), data)

    np.testing.assert_allclose(
        summed, build_dense_semianalytic_regularized_partition_jacobian(mesh, head, **kwargs)
    )
    # The unscaled coupling of the edge is -1.5 m2/s (thickness 1.25 m, head step 0.5 m). The
    # partition scales it by the release share, which lies between 0 and 1.
    assert -1.5 < summed[0, 1] < 0.0
