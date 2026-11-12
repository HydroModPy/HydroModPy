"""Boundary edge fluxes rebuilt from the heads imposed on edges or on cells, in m3/s.

The mesh is a row of three cells, 10 m wide, 10 m thick, with K = 1e-5 m/s. Edge 2 closes
cell 0 on the west and edge 3 closes cell 2 on the east. All heads are 5 m.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.assembly.boundary_flux_reconstruction import (
    rebuild_boundary_edge_flux,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from tests._helpers.boussinesq_cell_meshes import placeholder_cell_mesh


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


NAN = np.nan
K_M_S = 1.0e-5
HEAD_M = np.full(3, 5.0)
# Edge conductance K b L / d = 1e-5 m/s x 5 m x 10 m / 5 m = 1e-4 m2/s, flux = -1e-4 x (7 - 5).
WEST_FLUX_M3_S = -2.0e-4
BASE = {
    "head_m": HEAD_M,
    "assembly_boundary_edge_flux_m3_s": np.zeros(4),
    "boundary_head_m_by_edge": np.asarray([NAN, NAN, 7.0, NAN]),
    "prescribed_head_m_by_cell": np.asarray([7.0, NAN, NAN]),
}


def rebuilt(**changes) -> np.ndarray:
    return rebuild_boundary_edge_flux(mesh=row_of_three_cells(), **(BASE | changes))


CLOSURES = [
    pytest.param(
        {"assembly_boundary_edge_flux_m3_s": np.asarray([0.0, 0.0, 1.0e-4, 0.0])},
        id="assembly already carries a flux",
    ),
    pytest.param({"prescribed_head_m_by_cell": np.full(3, NAN)}, id="no cell prescribed"),
    pytest.param(
        {"prescribed_head_m_by_cell": np.asarray([NAN, 7.0, NAN])},
        id="supported cell is free",
    ),
]


@pytest.mark.parametrize("changes", CLOSURES)
def test_flux_stays_the_edge_head_flux(changes: dict) -> None:
    np.testing.assert_allclose(rebuilt(**changes), [0.0, 0.0, WEST_FLUX_M3_S, 0.0], rtol=1e-9)


REFUSALS = [
    pytest.param(
        {"assembly_boundary_edge_flux_m3_s": np.zeros(3)},
        "assembly_boundary_edge_flux_m3_s must have length",
        id="assembly flux size",
    ),
    pytest.param(
        {"boundary_head_m_by_edge": np.full(3, NAN)},
        "boundary_head_m_by_edge must have length",
        id="edge head size",
    ),
    pytest.param(
        {"prescribed_head_m_by_cell": np.full(2, NAN)},
        "prescribed_head_m_by_cell must have length",
        id="cell head size",
    ),
    pytest.param(
        {"internal_edge_flux_m3_s": np.zeros(3)},
        "internal_edge_flux_m3_s must have length",
        id="internal flux size",
    ),
    pytest.param(
        {"prescribed_head_flux_m3_s": np.zeros(2)},
        "prescribed_head_flux_m3_s must have length",
        id="cell flux size",
    ),
]


@pytest.mark.parametrize(("changes", "message"), REFUSALS)
def test_refusals(changes: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        rebuilt(**changes)
