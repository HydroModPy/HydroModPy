"""Sparse Jacobian triplets (data, rows, cols) of the Boussinesq residual operators.

Heads are in m, conductivities in m/s and the residual in m3/s. The mesh is two unit cells, 2 m
thick, joined by one edge 1 m long whose midpoint is 0.5 m from each cell centre.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.jacobian.operator_triplets import (
    append_boundary_head_triplets,
    build_sparse_semianalytic_triplets,
)
from tests._helpers.boussinesq_mesh_doubles import _MiniMesh

pytestmark = pytest.mark.fast


def two_cells(k_m_s=(1.0, 1.0)) -> _MiniMesh:
    return _MiniMesh(
        cell_area_m2=np.ones(2),
        z_top_m=np.full(2, 2.0),
        z_bottom_m=np.zeros(2),
        hydraulic_conductivity_m_s=np.asarray(k_m_s, dtype=float),
        storage_coefficient=np.full(2, 0.2),
        edge_ids=np.asarray([0]),
        edge_cell_a=np.asarray([0]),
        edge_cell_b=np.asarray([1]),
        edge_length_m=np.ones(1),
        edge_distance_m=np.ones(1),
        edge_midpoint_distance_to_cell_a_m=np.full(1, 0.5),
        edge_midpoint_distance_to_cell_b_m=np.full(1, 0.5),
    )


def triplets(mesh, head, *, boundary_head=None, dt=None, **flags):
    off = dict(
        include_storage=False,
        include_internal_flux=False,
        include_boundary_head_flux=False,
        include_drainage=False,
        include_prescribed_identity=False,
    )
    return build_sparse_semianalytic_triplets(
        mesh,
        np.asarray(head, dtype=float),
        dt_seconds=dt,
        boundary_head_m_by_edge=boundary_head,
        prescribed_head_m_by_cell=None,
        drainage_conductance_m2_s=None,
        **(off | flags),
    )


def test_boundary_head_on_an_interior_edge_loads_both_cells() -> None:
    # Boundary head 3 m on the edge. Conductance K L / d = 1 x 1 / 0.5 = 2 m2/s on each side.
    # Cell a, head 1 m: tau = 2 x 1 = 2 and dtau/dh = 2, so 2 - 2 x (3 - 1) = -2.
    # Cell b, head 1.5 m: tau = 2 x 1.5 = 3 and dtau/dh = 2, so 3 - 2 x (3 - 1.5) = 0.
    data, rows, cols = triplets(
        two_cells(), [1.0, 1.5], boundary_head=np.array([3.0]), include_boundary_head_flux=True
    )

    np.testing.assert_allclose(data, [-2.0, 0.0])
    assert rows.tolist() == cols.tolist() == [0, 1]


def test_dry_cell_beyond_a_boundary_head_has_no_entry() -> None:
    # Cell b is below its bottom: no thickness and no slope, so only cell a is loaded.
    data, rows, cols = triplets(
        two_cells(), [1.0, -1.0], boundary_head=np.array([3.0]), include_boundary_head_flux=True
    )

    np.testing.assert_allclose(data, [-2.0])
    assert rows.tolist() == cols.tolist() == [0]


def test_edge_without_conductivity_carries_no_flux() -> None:
    data, rows, cols = triplets(two_cells(k_m_s=(0.0, 1.0)), [1.0, 1.5], include_internal_flux=True)

    assert data.size == rows.size == cols.size == 0


REFUSALS = [
    pytest.param(
        lambda: triplets(two_cells(), [1.0, 1.0, 1.0]),
        r"head_m length must match mesh.n_cells \(3 != 2\)",
        id="head of the wrong length",
    ),
    pytest.param(
        lambda: triplets(two_cells(), [1.0, 1.0], dt=0.0, include_storage=True),
        "strictly positive",
        id="zero time step",
    ),
    pytest.param(
        lambda: append_boundary_head_triplets(
            two_cells(),
            np.array([1.0, 1.0]),
            np.ones(2),
            boundary_head_m_by_edge=np.array([3.0, 3.0]),
            data_parts=[],
            row_parts=[],
            col_parts=[],
        ),
        "Expected vector of length 1; got 2",
        id="boundary heads of the wrong length",
    ),
]


@pytest.mark.parametrize(("call", "message"), REFUSALS)
def test_refusals(call, message) -> None:
    with pytest.raises(ValueError, match=message):
        call()
