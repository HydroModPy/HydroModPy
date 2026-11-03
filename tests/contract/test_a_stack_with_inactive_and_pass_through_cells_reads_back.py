"""A layer stack that is not a set of full columns goes through build, store and read.

The stack is what a voxel or a pinched layer will produce: interfaces that vary
from cell to cell, a top layer inactive over part of the plan (``idomain = 0``)
and one vertical pass-through cell (``idomain = -1``). MODFLOW 6 solves it, the
extractor stores the interfaces and the ``idomain`` of every cell, and the run
reads back without knowing how its layers were built: the water table is the
head of the top active cell, the seepage follows it, a point without a layer
reads its top active cell, and the exports number the layers from 0.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr

from hydromodpy.core.vertical_column import VERTICAL_LAYOUT_COLUMN_FRACTIONS, top_active_layer
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive.reading import read_variable
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
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
from tests._helpers.run_stores import open_run_store
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

pytestmark = [pytest.mark.mf6, pytest.mark.binary, pytest.mark.allow_subprocess]

NROW, NCOL, NLAY = 3, 4, 3
N_CELLS = NROW * NCOL
STEP = 100.0
INACTIVE_TOP = (0, 4)
"""Columns whose top cell is inactive: their top active cell is in layer 1."""
PASS_THROUGH = 6
"""Column whose layer 1 cell is a pass-through between two active cells."""


def _stack() -> SolverMesh:
    rows, cols = np.divmod(np.arange(N_CELLS), NCOL)
    top = 100.0 + 2.0 * cols - 1.0 * rows
    first = top - 10.0 - 0.5 * np.arange(N_CELLS)
    second = first - 20.0 + 0.25 * cols
    third = second - 30.0
    idomain = np.ones((NLAY, N_CELLS), dtype=int)
    idomain[0, list(INACTIVE_TOP)] = 0
    idomain[1, PASS_THROUGH] = -1
    mesh = solver_mesh_from_structured_arrays(
        nrow=NROW, ncol=NCOL, top=top, botm=np.vstack([first, second, third]), dx=STEP, dy=STEP
    )
    return SolverMesh(cell_mesh=mesh.cell_mesh, top=mesh.top, botm=mesh.botm, idomain=idomain)


def _drains(mesh: SolverMesh) -> list[list[float]]:
    model = SimpleNamespace(
        dem_mask=mesh.closed_surface(),
        nper=1,
        ncpl=N_CELLS,
        hk=np.full((NLAY, N_CELLS), 1e-5),
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


def _solve(mesh: SolverMesh, ws: Path) -> np.ndarray:
    """Build and run the MODFLOW 6 model of ``mesh``; return the head, (nlay, n_cells)."""
    import flopy

    sim = flopy.mf6.MFSimulation(
        sim_name="m", sim_ws=str(ws), exe_name=str(ensure_solver_binary("mf6"))
    )
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m", save_flows=True)
    grid = disv_grid_kwargs(SimpleNamespace(solver_mesh=mesh, open_water_cell_ids=[]))
    flopy.mf6.ModflowGwfdisv(gwf, **grid)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1e-5, k33=1e-6)
    flopy.mf6.ModflowGwfic(gwf, strt=95.0)
    west = [c for c in range(N_CELLS) if c % NCOL == 0]
    chd = [[(k, c), 80.0] for k in range(NLAY) for c in west if int(mesh.idomain[k, c]) > 0]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd})
    flopy.mf6.ModflowGwfdrn(
        gwf, stress_period_data={0: [[(int(r[0]), int(r[1])), r[2], r[3]] for r in _drains(mesh)]}
    )
    flopy.mf6.ModflowGwfrcha(gwf, recharge=2e-8)
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord="m.hds", saverecord=[("HEAD", "ALL")])
    sim.write_simulation(silent=True)
    success, _ = sim.run_simulation(silent=True)
    assert success
    head = flopy.utils.HeadFile(str(ws / "m.hds")).get_data()
    return np.asarray(head, dtype=float).reshape(NLAY, N_CELLS)


class _Handle:
    """A store handle the extractor may close without closing the test's store."""

    def __init__(self, store) -> None:
        self._store = store

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def close(self) -> None:
        return None


@pytest.fixture(scope="module")
def stack_run(tmp_path_factory) -> SimpleNamespace:
    """Solve the stack, store it as the pipeline does, seal and index it."""
    ws = tmp_path_factory.mktemp("mf6")
    mesh = _stack()
    head = _solve(mesh, ws)
    np.savez(ws / f"m{GROUND_SIDECAR_SUFFIX}", ground=mesh.top)

    project = tmp_path_factory.mktemp("project")
    store = open_run_store(
        project, "stack", n_cells=N_CELLS, n_layers=NLAY, n_timesteps=1, crs_epsg=2154
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
    store.write_time(sid, np.array([0], dtype="int64"))
    store.write_field(sid, "head", 0, head, n_timesteps=1)
    Modflow6OutputAdapter()._write_surface_elevation(
        sid,
        SimpleNamespace(open_zarr=lambda sim_id: _Handle(store.open_zarr(sim_id))),
        ws,
        "m",
        NLAY,
        N_CELLS,
    )
    seal_completed(store)
    rebuild_index(project)
    return SimpleNamespace(project=project, sid=sid, mesh=mesh, head=head)


@pytest.fixture
def run(stack_run):
    with Catalog(stack_run.project) as catalog:
        yield catalog[stack_run.sid]


def test_the_solver_leaves_no_head_in_the_cells_it_does_not_compute(stack_run) -> None:
    computed = np.abs(stack_run.head) < 1e20
    assert np.array_equal(computed, stack_run.mesh.idomain > 0)


def test_the_store_keeps_the_interfaces_and_the_idomain_of_every_cell(stack_run, run) -> None:
    mesh = stack_run.mesh
    stored = run.mesh
    assert stored.z_interfaces.shape == (NLAY + 1, N_CELLS)
    np.testing.assert_allclose(stored.z_interfaces[0], mesh.top)
    np.testing.assert_allclose(stored.z_interfaces[1:], mesh.botm)
    np.testing.assert_array_equal(run.field("idomain"), mesh.idomain)
    np.testing.assert_array_equal(read_variable(run, "idomain"), mesh.idomain)
    np.testing.assert_allclose(run.field("layer_thickness"), mesh.layer_thicknesses())


def test_the_store_says_its_schema_and_how_its_layers_were_built(stack_run, run) -> None:
    sz = run._catalog.open_zarr(stack_run.sid)
    try:
        assert sz.root.attrs["zarr_schema_version"] == ZARR_SCHEMA_VERSION == "4"
        assert sz.root["mesh"].attrs["vertical_layout"] == VERTICAL_LAYOUT_COLUMN_FRACTIONS
        assert sz.root["mesh"]["idomain"].dtype == np.int8
    finally:
        sz.close()


def test_the_water_table_is_the_head_of_the_top_active_cell(stack_run, run) -> None:
    layer = top_active_layer(stack_run.mesh.idomain)
    expected = stack_run.head[layer, np.arange(N_CELLS)]
    assert layer[list(INACTIVE_TOP)].tolist() == [1, 1]
    assert layer[PASS_THROUGH] == 0
    # The store keeps fields in float32 with a rounded mantissa.
    np.testing.assert_allclose(run.field("watertable_elevation", timestep=0), expected, atol=1e-3)


def test_the_seepage_follows_the_water_table_and_the_ground(stack_run, run) -> None:
    water_table = np.asarray(run.field("watertable_elevation", timestep=0))
    seepage = np.asarray(run.field("seepage_mask", timestep=0))
    assert seepage.shape == (N_CELLS,)
    np.testing.assert_array_equal(seepage > 0, water_table >= stack_run.mesh.top)


def test_a_point_without_a_layer_reads_its_top_active_cell(stack_run, run) -> None:
    cell = INACTIVE_TOP[1]
    table = run.probe.series("head", cell=cell)
    assert table["layer"].unique().tolist() == [1]
    assert table["value"].iloc[0] == pytest.approx(stack_run.head[1, cell], abs=1e-3)


def test_the_exports_number_the_layers_from_zero(stack_run, run) -> None:
    (out,) = run.export(["head", "idomain"], format="netcdf", file="stack.nc")
    with xr.open_dataset(out) as ds:
        assert ds["head"].dims == ("time", "layer", "n_face")
        np.testing.assert_array_equal(ds["layer"].values, np.arange(NLAY))
        np.testing.assert_array_equal(ds["idomain"].sel(layer=1).values, stack_run.mesh.idomain[1])
        assert ds["z_interfaces"].dims == ("n_z_interface", "n_face")
        assert ds["z_interfaces"].shape == (NLAY + 1, N_CELLS)
