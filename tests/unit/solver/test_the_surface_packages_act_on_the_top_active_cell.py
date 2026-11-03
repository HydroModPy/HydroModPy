"""Drains, evapotranspiration, the computational top and the sink mask read the top active cell.

Under a stack whose top layer is inactive in a column (a pinched or voxel
layer), the surface processes act on the first active cell below. A lake
footprint stays closed: LAK owns its surface.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    build_drain_stress_period_data,
)
from hydromodpy.solver.modflow6.builders.recharge import evt_surface
from hydromodpy.solver.modflow6.support.computational_top import raised_cells
from hydromodpy.solver.modflow_common.sink_mask import closed_depression_mask
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

N_CELLS = 4
TOP = np.array([10.0, 9.0, 8.0, 7.0])
BOTM = np.vstack([TOP - 3.0, TOP - 10.0])


def _mesh(idomain: np.ndarray) -> SolverMesh:
    base = solver_mesh_from_structured_arrays(nrow=1, ncol=N_CELLS, top=TOP, botm=BOTM)
    return SolverMesh(cell_mesh=base.cell_mesh, top=base.top, botm=base.botm, idomain=idomain)


def _drain_model(mesh: SolverMesh, covered=()) -> SimpleNamespace:
    return SimpleNamespace(
        dem_mask=mesh.closed_surface(covered),
        nper=1,
        ncpl=N_CELLS,
        hk=np.vstack([np.full(N_CELLS, 1e-4), np.full(N_CELLS, 1e-5)]),
        sink_fill=False,
        sink=None,
        drain_band_depth_m=0.0,
        drain_bed_thickness_m=1.0,
        drain_conductance_floor_m2_s=1e-12,
    )


def test_a_drain_sits_on_the_top_active_cell_with_its_top_and_its_conductivity() -> None:
    mesh = _mesh(np.array([[1, 0, 1, 0], [1, 1, 1, 0]]))
    rows = build_drain_stress_period_data(
        _drain_model(mesh),
        solver_mesh=mesh,
        drainage_cond_series=np.array([0.0]),
        ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
        stream_support_mask=np.zeros(N_CELLS, dtype=bool),
    )[0]

    by_cell = {int(row[1]): row for row in rows}
    assert sorted(by_cell) == [0, 1, 2]
    assert by_cell[0][0] == 0
    assert by_cell[1][0] == 1
    assert by_cell[1][2] == BOTM[0, 1]
    # hk * area / bed: the conductivity of layer 1 for the cell whose top is inactive.
    assert by_cell[1][3] == 1e-5 * mesh.cell_areas()[1] / 1.0


def test_a_lake_footprint_gets_no_drain() -> None:
    mesh = _mesh(np.array([[1, 0, 1, 1], [1, 1, 1, 1]]))
    rows = build_drain_stress_period_data(
        _drain_model(mesh, covered=[1]),
        solver_mesh=mesh,
        drainage_cond_series=np.array([1e-3]),
        ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
        stream_support_mask=np.zeros(N_CELLS, dtype=bool),
    )[0]
    assert sorted(int(row[1]) for row in rows) == [0, 2, 3]


def test_the_evapotranspiration_surface_is_the_top_of_the_top_active_cell() -> None:
    mesh = _mesh(np.array([[1, 0, 1, 0], [1, 1, 1, 0]]))
    surface = evt_surface(mesh, np.array([True, True, False, True]))
    # Kept cells read their top active cell; the others keep the model top.
    assert surface.tolist() == [10.0, BOTM[0, 1], 8.0, 7.0]


def test_only_a_column_whose_top_active_cell_is_in_layer_zero_is_raised() -> None:
    mesh = _mesh(np.array([[1, 0, 1, 1], [1, 1, 1, 1]]))
    assert raised_cells(mesh, open_water_cell_ids=[3]).tolist() == [True, False, True, False]


def test_a_covered_column_is_closed_to_the_sink_flood() -> None:
    top = np.full(9, 10.0)
    top[4] = 5.0
    base = solver_mesh_from_structured_arrays(nrow=3, ncol=3, top=top, botm=top - 20.0)
    # The center is a pit ringed by higher cells; covered by a lake, it is no pit.
    assert np.flatnonzero(closed_depression_mask(base)).tolist() == [4]
    assert not closed_depression_mask(base, covered_cells=[4]).any()
