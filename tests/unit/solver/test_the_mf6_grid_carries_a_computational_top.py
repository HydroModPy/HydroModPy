"""MODFLOW 6 reads a computational top; the solver mesh and the store keep the ground.

Under Newton, MF6 weights the horizontal conductance by the full thickness of the
two cells. The DISV therefore carries T' = G + (Dmax - D), which gives every
raised cell of the top layer the same thickness, and G everywhere else.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.solver.modflow6.support.computational_top import (
    GROUND_SIDECAR_SUFFIX,
    computational_top,
    disv_grid_kwargs,
    model_computational_top,
    read_ground_sidecar,
    well_flow_reduce_fraction,
    write_ground_sidecar,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from tests._helpers.ugrid_meshes import quad_mesh

GROUND = np.array([12.0, 10.5, 9.0, 7.25, 6.0, 4.0])
SUBSTRATUM = -5.0


def _mesh(ground, botm, *, inactive=None) -> SolverMesh:
    vertices, connectivity = quad_mesh(1, len(ground))
    botm = np.atleast_2d(np.asarray(botm, dtype=float))
    return SolverMesh(
        planar_mesh=HydroMesh(
            vertices=vertices[:, :2],
            cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
        ),
        top=np.asarray(ground, dtype=float),
        botm=botm,
        inactive_mask=np.zeros(botm.shape, dtype=bool) if inactive is None else inactive,
    )


def _model(solver_mesh: SolverMesh, *, lakes=(), folder: Path | None = None):
    return SimpleNamespace(
        solver_mesh=solver_mesh,
        open_water_cell_ids=list(lakes),
        full_path=str(folder) if folder else None,
        model_output_name="flow",
    )


def test_a_constant_thickness_gives_the_ground_back_exactly() -> None:
    ground = GROUND + np.array([0.1, 0.2, 0.3, 0.7, 0.9, 0.11])
    top = computational_top(ground, ground - 30.0, np.ones(ground.size, dtype=bool))
    assert np.array_equal(top, ground)


def test_a_flat_substratum_gets_one_thickness_everywhere() -> None:
    bottom = np.full(GROUND.size, SUBSTRATUM)
    top = computational_top(GROUND, bottom, np.ones(GROUND.size, dtype=bool))
    np.testing.assert_allclose(top - bottom, GROUND.max() - SUBSTRATUM, rtol=0, atol=1e-12)
    assert top[0] == GROUND[0]


def test_a_deficit_under_a_millimetre_is_no_deficit() -> None:
    ground = np.array([10.0, 9.9991, 9.9989])
    top = computational_top(ground, np.zeros(3), np.ones(3, dtype=bool))
    assert top[1] == ground[1]
    assert top[2] == pytest.approx(10.0, abs=1e-12)


def test_a_raised_cell_without_a_finite_ground_is_refused() -> None:
    ground = GROUND.copy()
    ground[2] = np.nan
    with pytest.raises(ValueError, match="finite"):
        computational_top(ground, np.full(GROUND.size, SUBSTRATUM), np.ones(GROUND.size, bool))


def test_a_lake_column_and_an_inactive_cell_keep_their_ground() -> None:
    inactive = np.zeros((1, GROUND.size), dtype=bool)
    inactive[0, 5] = True
    mesh = _mesh(GROUND, np.full((1, GROUND.size), SUBSTRATUM), inactive=inactive)
    top = model_computational_top(_model(mesh, lakes=[3]))
    assert top[3] == GROUND[3]
    assert top[5] == GROUND[5]
    raised = [0, 1, 2, 4]
    np.testing.assert_allclose(top[raised] - SUBSTRATUM, GROUND.max() - SUBSTRATUM)


def test_only_the_top_of_the_first_layer_moves() -> None:
    bottom = np.full(GROUND.size, SUBSTRATUM)
    botm = np.vstack([GROUND - 0.5 * (GROUND - bottom), bottom])
    mesh = _mesh(GROUND, botm)
    kwargs = disv_grid_kwargs(_model(mesh))

    assert kwargs["nlay"] == 2
    np.testing.assert_array_equal(kwargs["botm"], botm)
    layer_0 = kwargs["top"] - botm[0]
    np.testing.assert_allclose(layer_0, layer_0.max())
    np.testing.assert_array_equal(mesh.top, GROUND)
    assert kwargs["xorigin"] == kwargs["yorigin"] == 0.0
    np.testing.assert_array_equal(kwargs["idomain"], mesh.idomain())


def test_the_well_turnoff_stays_a_tenth_of_the_aquifer() -> None:
    mesh = _mesh(GROUND, np.full((1, GROUND.size), SUBSTRATUM))
    model = _model(mesh)
    top = model_computational_top(model)
    wells = {0: [[0, 1, -1.0], [0, 4, -2.0]], 1: [[0, 4, -2.0]]}

    fraction = well_flow_reduce_fraction(model, wells, of_aquifer=0.1)

    aquifer = GROUND - SUBSTRATUM
    interval = fraction * (top - SUBSTRATUM)
    assert np.all(interval[[1, 4]] <= 0.1 * aquifer[[1, 4]] + 1e-12)
    assert interval[4] == pytest.approx(0.1 * aquifer[4])


def test_a_well_below_the_top_layer_or_a_constant_thickness_keeps_a_tenth() -> None:
    bottom = np.full(GROUND.size, SUBSTRATUM)
    two_layers = _model(_mesh(GROUND, np.vstack([GROUND - 2.0, bottom])))
    assert well_flow_reduce_fraction(two_layers, {0: [[1, 4, -1.0]]}, of_aquifer=0.1) == 0.1

    constant = _model(_mesh(GROUND, GROUND - 20.0))
    assert well_flow_reduce_fraction(constant, {0: [[0, 4, -1.0]]}, of_aquifer=0.1) == 0.1


def test_the_ground_file_round_trips_and_refuses_what_does_not_fit(tmp_path: Path) -> None:
    mesh = _mesh(GROUND, np.full((1, GROUND.size), SUBSTRATUM))
    model = _model(mesh, folder=tmp_path)
    written_top = model_computational_top(model)

    path = write_ground_sidecar(model)

    assert path.name == f"flow{GROUND_SIDECAR_SUFFIX}"
    np.testing.assert_array_equal(read_ground_sidecar(tmp_path, written_top=written_top), GROUND)
    with pytest.raises(SolverInputError, match="ground above the top"):
        read_ground_sidecar(tmp_path, written_top=written_top - 1.0)
    with pytest.raises(SolverInputError, match="holds 6 cells"):
        read_ground_sidecar(tmp_path, written_top=written_top[:4])
    np.savez(tmp_path / f"other{GROUND_SIDECAR_SUFFIX}", ground=GROUND)
    with pytest.raises(SolverInputError, match="must hold one"):
        read_ground_sidecar(tmp_path, written_top=written_top)


class _Handle:
    """Hands out ``store`` to an extractor that closes what it opens."""

    def __init__(self, store: SimulationZarr) -> None:
        self._store = store

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def close(self) -> None:
        return None


def _fake_grid_file(monkeypatch, tmp_path: Path, *, top: np.ndarray, bot: np.ndarray) -> None:
    import flopy.mf6.utils

    xs, ys = np.meshgrid(np.arange(GROUND.size + 1.0), np.arange(2.0))

    class _FakeGrid:
        grid_type = "dis"
        top1d = top
        bot1d = bot
        modelgrid = SimpleNamespace(xvertices=xs, yvertices=ys)

        def __init__(self, path: str) -> None:
            del path

    monkeypatch.setattr(flopy.mf6.utils, "MfGrdFile", _FakeGrid)
    (tmp_path / "flow.dis.grb").write_bytes(b"")


def _write_surface(tmp_path: Path, store: SimulationZarr) -> None:
    from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter

    Modflow6OutputAdapter()._write_surface_elevation(
        "sim",
        SimpleNamespace(open_zarr=lambda sim_id: _Handle(store)),
        tmp_path,
        "flow",
        1,
        GROUND.size,
        grid_shape=(1, GROUND.size),
    )


def test_the_store_keeps_the_ground_not_the_computational_top(tmp_path, monkeypatch) -> None:
    pytest.importorskip("flopy")
    bottom = np.full(GROUND.size, SUBSTRATUM)
    model = _model(_mesh(GROUND, bottom), folder=tmp_path)
    _fake_grid_file(monkeypatch, tmp_path, top=model_computational_top(model), bot=bottom)
    write_ground_sidecar(model)
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=GROUND.size, n_layers=1)
    try:
        _write_surface(tmp_path, store)

        mesh = store.root["mesh"]
        np.testing.assert_array_equal(mesh["topography"][:], GROUND)
        np.testing.assert_array_equal(mesh["layer_thickness"][:][0], GROUND - SUBSTRATUM)
        assert mesh["z_interfaces"][:][0] == GROUND[0]
    finally:
        store.close()


def test_a_grid_file_without_its_ground_is_refused(tmp_path, monkeypatch) -> None:
    pytest.importorskip("flopy")
    bottom = np.full(GROUND.size, SUBSTRATUM)
    _fake_grid_file(monkeypatch, tmp_path, top=GROUND, bot=bottom)
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=GROUND.size, n_layers=1)
    try:
        with pytest.raises(SolverInputError, match="computational top"):
            _write_surface(tmp_path, store)
    finally:
        store.close()


def _flow_model(tmp_path: Path, ground: np.ndarray):
    """A built GWF DISV on a row of cells whose thickness varies, as the build makes it."""
    import flopy

    from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config

    mesh = _mesh(ground, np.zeros((1, ground.size)))
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="seconds")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])
    model = _model(mesh, folder=tmp_path)
    flopy.mf6.ModflowGwfdisv(gwf, **disv_grid_kwargs(model))
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0)
    rch = flopy.mf6.ModflowGwfrcha(
        gwf,
        recharge={0: 1e-8},
        auxiliary=["CONCENTRATION"],
        aux={0: [np.zeros(ground.size)]},
        pname="RCHA",
    )
    for name, value in dict(
        sim=sim,
        gwf=gwf,
        ims=ims,
        rch=rch,
        nlay=1,
        ncpl=ground.size,
        nper=1,
        sy=np.full((1, ground.size), 0.1),
        model_name="flow",
        exe="mf6",
        modflow_config=_coerce_modflow6_config(None),
    ).items():
        setattr(model, name, value)
    return model


def test_the_transport_and_tracking_grids_carry_the_flow_top(tmp_path) -> None:
    pytest.importorskip("flopy")
    from hydromodpy.physics.transport.transport import Transport
    from hydromodpy.solver.modflow6.prt import Modflow6Prt
    from hydromodpy.solver.modflow6.transport import Modflow6Transport

    flow = _flow_model(tmp_path / "gwt", GROUND)
    gwt = Modflow6Transport(
        SimpleNamespace(),
        Transport({"modflow6gwt": {"parameters": {"porosity": 0.3}}}),
        flow,
        str(tmp_path / "gwt"),
        "flow",
    )
    gwt.pre_processing()
    flow_top = np.asarray(flow.gwf.disv.top.array)
    np.testing.assert_array_equal(np.asarray(gwt.gwtdis.top.array), flow_top)

    flow = _flow_model(tmp_path / "prt", GROUND)
    prt = Modflow6Prt(
        SimpleNamespace(),
        Transport({"modflow6prt": {"parameters": {"release_zone": "domain", "porosity": 0.3}}}),
        flow,
        str(tmp_path / "prt"),
        "flow",
    )
    prt.pre_processing()
    np.testing.assert_array_equal(np.asarray(prt.prtdis.top.array), flow_top)
    assert np.all(flow_top >= GROUND) and np.any(flow_top > GROUND)
