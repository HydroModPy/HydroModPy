"""MODFLOW 6 solves a stack whose weathered layer pinches out into pass-through cells.

The weathered layer thins out to the east and its thin cells become ``idomain =
-1``. MODFLOW 6 converges, computes a head only in the active cells, the drains
sit on the top active cell of each column, the recharge reaches the active cell
under a pass-through cell through the layer array the build writes (MODFLOW 6
drops it otherwise), and the store keeps the
``idomain`` and says the layers were built by surfaces.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.vertical_column import VERTICAL_LAYOUT_SURFACES, top_active_layer
from hydromodpy.solver.modflow6.builders import areal_layer_index
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    build_drain_stress_period_data,
)
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow6.support.computational_top import (
    GROUND_SIDECAR_SUFFIX,
    disv_grid_kwargs,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import VerticalGridConfig
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_generation import layer_stack
from tests._helpers.run_stores import open_run_store
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

pytestmark = [pytest.mark.mf6, pytest.mark.binary, pytest.mark.allow_subprocess]

NROW, NCOL = 3, 6
N_CELLS = NROW * NCOL
STEP = 100.0
RECHARGE_M_S = 2e-8
WEATHERED_M = np.tile(np.linspace(6.0, 0.0, NCOL), NROW)
"""Thickness of the weathered layer under every cell: it vanishes to the east."""


def _stack() -> SolverMesh:
    cols = np.arange(N_CELLS) % NCOL
    top = 100.0 - 1.0 * cols
    layers = VerticalGridConfig.model_validate(
        {
            "genmtd_lay": "surfaces",
            "layer": [
                {"name": "weathered", "surface": "weathered_base", "min_thickness": 1.0},
                {"name": "fissured", "thickness": 20.0},
                {"name": "rock"},
            ],
        }
    )
    stack = layer_stack(
        top=top,
        bottom=top - 60.0,
        invalid=np.zeros(N_CELLS, dtype=bool),
        vertical_config=layers,
        bases={"weathered_base": top - WEATHERED_M},
        nodata=-9999.0,
    )
    mesh = solver_mesh_from_structured_arrays(
        nrow=NROW, ncol=NCOL, top=top, botm=stack.botm, dx=STEP, dy=STEP
    )
    return SolverMesh(cell_mesh=mesh.cell_mesh, top=mesh.top, botm=mesh.botm, idomain=stack.idomain)


def _drains(mesh: SolverMesh) -> list[list[float]]:
    model = SimpleNamespace(
        dem_mask=mesh.closed_surface(),
        nper=1,
        ncpl=N_CELLS,
        hk=np.full((mesh.nlay, N_CELLS), 1e-5),
        sink_fill=False,
        sink=None,
        drain_band_depth_m=0.0,
        drain_bed_thickness_m=1.0,
        drain_conductance_floor_m2_s=1e-12,
    )
    return build_drain_stress_period_data(
        model,
        solver_mesh=mesh,
        drainage_cond_series=np.array([1e-3]),
        ocean_support_mask=np.zeros(N_CELLS, dtype=bool),
        stream_support_mask=np.zeros(N_CELLS, dtype=bool),
    )[0]


@pytest.fixture(scope="module")
def solved(tmp_path_factory) -> SimpleNamespace:
    import flopy

    ws = tmp_path_factory.mktemp("mf6")
    mesh = _stack()
    drains = _drains(mesh)
    sim = flopy.mf6.MFSimulation(
        sim_name="m", sim_ws=str(ws), exe_name=str(ensure_solver_binary("mf6"))
    )
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m", save_flows=True)
    flopy.mf6.ModflowGwfdisv(
        gwf, **disv_grid_kwargs(SimpleNamespace(solver_mesh=mesh, open_water_cell_ids=[]))
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1e-5, k33=1e-6)
    flopy.mf6.ModflowGwfic(gwf, strt=90.0)
    west = [c for c in range(N_CELLS) if c % NCOL == 0]
    chd = [[(k, c), 85.0] for k in range(mesh.nlay) for c in west if int(mesh.idomain[k, c]) > 0]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd})
    flopy.mf6.ModflowGwfdrn(
        gwf, stress_period_data={0: [[(int(r[0]), int(r[1])), r[2], r[3]] for r in drains]}
    )
    flopy.mf6.ModflowGwfrcha(
        gwf, recharge=RECHARGE_M_S, irch=areal_layer_index(mesh), save_flows=True
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="m.hds",
        budget_filerecord="m.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    success, _ = sim.run_simulation(silent=True)
    head = np.asarray(flopy.utils.HeadFile(str(ws / "m.hds")).get_data(), dtype=float)
    budget = flopy.utils.CellBudgetFile(str(ws / "m.cbc"))
    recharge = budget.get_data(text="RCH")[0]
    np.savez(ws / f"m{GROUND_SIDECAR_SUFFIX}", ground=mesh.top)
    return SimpleNamespace(
        ws=ws,
        mesh=mesh,
        success=success,
        head=head.reshape(mesh.nlay, N_CELLS),
        drains=drains,
        recharge=recharge,
    )


def test_the_weathered_layer_pinches_out_where_it_thins_out(solved) -> None:
    thin = WEATHERED_M < 1.0
    np.testing.assert_array_equal(solved.mesh.idomain[0], np.where(thin, -1, 1))
    assert (solved.mesh.idomain[1:] == 1).all()


def test_modflow6_converges_and_computes_only_the_active_cells(solved) -> None:
    assert solved.success
    computed = np.abs(solved.head) < 1e20
    np.testing.assert_array_equal(computed, solved.mesh.idomain > 0)


def test_the_drains_sit_on_the_top_active_cell_of_each_column(solved) -> None:
    top_layer = top_active_layer(solved.mesh.idomain)
    layers = {int(row[1]): int(row[0]) for row in solved.drains}
    assert sorted(layers) == list(range(N_CELLS))
    assert all(layers[c] == top_layer[c] for c in range(N_CELLS))
    assert set(top_layer.tolist()) == {0, 1}


def test_the_recharge_reaches_the_active_cell_under_a_pass_through_cell(solved) -> None:
    nodes = np.asarray(solved.recharge["node"], dtype=int) - 1
    rates = np.asarray(solved.recharge["q"], dtype=float)
    columns = nodes % N_CELLS
    layers = nodes // N_CELLS
    expected = RECHARGE_M_S * STEP * STEP
    assert sorted(columns.tolist()) == list(range(N_CELLS))
    # A constant-head cell takes no recharge: the western column holds them.
    free = columns % NCOL != 0
    np.testing.assert_allclose(rates[free], expected, rtol=1e-12)
    np.testing.assert_array_equal(layers, top_active_layer(solved.mesh.idomain)[columns])


def test_the_store_keeps_the_idomain_and_says_the_layers_were_built_by_surfaces(
    solved, tmp_path: Path
) -> None:
    mesh = solved.mesh
    store = open_run_store(
        tmp_path, "pinched", n_cells=N_CELLS, n_layers=mesh.nlay, n_timesteps=1, crs_epsg=2154
    )
    sid = store.sim_id
    vertices = np.asarray(mesh.planar_mesh.vertices, dtype=float)[:, :2]
    sz = store.open_zarr(sid)
    try:
        sz.write_mesh(
            np.column_stack([vertices, np.zeros(len(vertices))]),
            mesh.cell_mesh.connectivity_rows,
            np.tile([[0.0], [-1.0]], (1, N_CELLS)),
            structured_shape=(NROW, NCOL),
        )
    finally:
        sz.close()
    Modflow6OutputAdapter()._write_surface_elevation(
        sid,
        store,
        solved.ws,
        "m",
        mesh.nlay,
        N_CELLS,
        vertical_layout=VERTICAL_LAYOUT_SURFACES,
    )
    sz = store.open_zarr(sid)
    try:
        assert sz.root["mesh"].attrs["vertical_layout"] == VERTICAL_LAYOUT_SURFACES
        np.testing.assert_array_equal(np.asarray(sz.root["mesh"]["idomain"]), mesh.idomain)
        np.testing.assert_allclose(np.asarray(sz.root["mesh"]["z_interfaces"])[1:], mesh.botm)
    finally:
        sz.close()
