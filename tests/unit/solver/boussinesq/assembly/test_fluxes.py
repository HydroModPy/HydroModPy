"""Edge and cell fluxes of the Boussinesq assembly, in m3/s, from heads in m.

The mesh is a row of three cells, 10 m wide, joined by two interior edges and closed by
one boundary edge at each end. Every cell is 10 m thick with K = 1e-5 m/s.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.assembly.fluxes import (
    accumulate_boundary_flux_residual,
    harmonic_conductivity,
    transmissivity_from_head,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from tests._helpers.boussinesq_cell_meshes import placeholder_cell_mesh

K_M_S = 1.0e-5


def row_of_three_cells() -> BoussinesqMesh:
    """Cells 0, 1, 2 in a row. Edges 0 and 1 are interior, edges 2 and 3 are boundaries."""
    return BoussinesqMesh(
        bundle_dir=Path("."),
        cell_ids=np.arange(3),
        node_ids=np.arange(4),
        node_x_m=np.asarray([0.0, 1.0, 2.0, 3.0]),
        node_y_m=np.zeros(4),
        cell_node_ids=((0, 1, 2), (1, 2, 3), (2, 3, 0)),
        cell_centroid_x_m=np.asarray([5.0, 15.0, 25.0]),
        cell_centroid_y_m=np.zeros(3),
        cell_area_m2=np.full(3, 100.0),
        z_top_m=np.full(3, 10.0),
        z_bottom_m=np.zeros(3),
        hydraulic_conductivity_m_s=np.full(3, K_M_S),
        storage_coefficient=np.full(3, 0.1),
        edge_ids=np.arange(4),
        edge_node_a=np.asarray([1, 2, 0, 3]),
        edge_node_b=np.asarray([2, 3, 1, 2]),
        edge_cell_a=np.asarray([0, 1, 0, 2]),
        edge_cell_b=np.asarray([1, 2, -1, -1]),
        edge_length_m=np.full(4, 10.0),
        edge_distance_m=np.asarray([10.0, 10.0, 5.0, 5.0]),
        edge_midpoint_distance_to_cell_a_m=np.full(4, 5.0),
        edge_midpoint_distance_to_cell_b_m=np.asarray([5.0, 5.0, np.nan, np.nan]),
        edge_midpoint_x_m=np.asarray([10.0, 20.0, 0.0, 30.0]),
        edge_midpoint_y_m=np.zeros(4),
        edge_kind=("internal", "internal", "boundary", "boundary"),
        edge_is_river=np.zeros(4, dtype=bool),
        cell_index_by_id={0: 0, 1: 1, 2: 2},
        node_index_by_id={0: 0, 1: 1, 2: 2, 3: 3},
        cell_mesh=placeholder_cell_mesh(3),
    )


def test_transmissivity_is_k_times_thickness() -> None:
    # Heads of 5 m, 12 m (above the top, capped at 10 m) and -1 m (below the bottom, dry).
    transmissivity = transmissivity_from_head(row_of_three_cells(), np.asarray([5.0, 12.0, -1.0]))

    np.testing.assert_allclose(transmissivity, [5.0e-5, 1.0e-4, 0.0], rtol=1e-12)


HARMONIC_MEANS = [
    pytest.param(1.0e-5, 1.0e-5, 1.0e-5, id="equal"),
    pytest.param(1.0e-5, 3.0e-5, 1.5e-5, id="unequal"),  # 2 / (1e5 + 1/3e-5 s/m)
    pytest.param(0.0, 1.0e-5, 0.0, id="one impervious"),
    pytest.param(1.0e-5, -1.0e-5, 0.0, id="negative"),
]


@pytest.mark.parametrize(("k_a", "k_b", "expected"), HARMONIC_MEANS)
def test_harmonic_conductivity(k_a: float, k_b: float, expected: float) -> None:
    assert harmonic_conductivity(k_a, k_b) == pytest.approx(expected, rel=1e-9)


def test_boundary_flux_goes_to_its_cell() -> None:
    # Edges 0 and 1 are interior and carry no boundary flux.
    edge_flux_m3_s = np.asarray([7.0, 8.0, 2.0, 3.0])

    residual = accumulate_boundary_flux_residual(row_of_three_cells(), edge_flux_m3_s)

    np.testing.assert_allclose(residual, [2.0, 0.0, 3.0])
