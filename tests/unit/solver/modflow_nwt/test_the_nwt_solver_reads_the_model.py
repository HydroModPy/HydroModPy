"""``ModflowNwt`` reads the frozen ``Model`` it is given and nothing else.

The raster geometry gives its DEM grid and its routing settings, the channel
rasters give the generated river network, the catchment says where it closes,
and the time gives the regime and the first steady period. The steady
initialization runs on ``steady_variant`` of that model and leaves it as it was.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.terrain.port import CappedBreach
from hydromodpy.model.domain.geometry import CatchmentGeometry, ChannelRasters, RasterGeometry
from hydromodpy.model.initial.state import (
    CyclicStart,
    HeadRule,
    SteadyStart,
    SteadyStateStrategy,
)
from hydromodpy.model.model import Geometry, Model, ModelTime, Properties
from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.modflow_common.flow_run import build_preprocess_options
from hydromodpy.solver.modflow_common.options import ModflowPreprocessOptions, ModflowRunOptions
from hydromodpy.solver.modflow_nwt.nwt import nwt_solver, steady_initial_conditions
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from tests._helpers.model_factory import make_model, small_geometry, time_grid
from tests._helpers.regular_cell_meshes import regular_cell_mesh_of_surface
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

from .test_modflow_domain_surfaces import _build_domain_from_dem, _DummyGeographic

CHANNEL = ChannelRasters(enabled=True, link="link.tif", pointer="ptr.tif", accumulation="acc.tif")
OUTLET = (12.0, 34.0)


def _geographic(**members) -> SimpleNamespace:
    base = {
        "dem_res": 10.0,
        "xmin": 0.0,
        "ymax": 20.0,
        "dem_data": np.zeros((2, 3)),
        "dem_box_buff_data": np.zeros((2, 3)),
        "watershed_buff_dem": "buff.tif",
        "watershed_box_buff_dem": "box.tif",
        "crs_proj": "EPSG:2154",
        "terrain_engine": "whitebox",
        "dem_correc_type": "fill",
        "catch_def": "outlet",
        "x_outlet": OUTLET[0],
        "y_outlet": OUTLET[1],
    }
    return SimpleNamespace(**(base | members))


def _model(*, geographic=None, **members) -> Model:
    geographic = _geographic() if geographic is None else geographic
    geometry = Geometry(
        cells=small_geometry().cells,
        domain=object(),
        raster=RasterGeometry.from_geographic(geographic, channel=CHANNEL),
        catchment=CatchmentGeometry.from_geographic(geographic, crs="EPSG:2154"),
    )
    return make_model(geometry=geometry, **members)


def _solver(model: Model, tmp_path) -> ModflowNwt:
    solver = ModflowNwt(model_folder=str(tmp_path))
    solver.inputs = model
    return solver


def test_the_routing_context_is_built_from_the_raster_geometry(monkeypatch, tmp_path) -> None:
    breach = SimpleNamespace(max_depth=2.0, max_distance=30.0)
    geographic = _geographic(dem_correc_type="capped_breach", capped_breach=breach)
    solver = _solver(_model(geographic=geographic), tmp_path)
    solver.grid_ctx = SimpleNamespace()
    solver.dem_watershed_path = "dem.tif"
    captured: dict = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(nwt_solver, "build_solver_routing_context", fake_build)

    solver._ensure_solver_routing_context()

    assert captured["dem_path"] == "dem.tif"
    assert captured["dem_correc_type"] == "capped_breach"
    assert captured["crs_project"] == "EPSG:2154"
    assert captured["engine_id"] == "whitebox"
    assert captured["capped_breach"] == CappedBreach(max_depth_m=2.0, max_distance_m=30.0)


def test_the_descent_reads_the_channel_rasters_and_the_catchment_of_the_model(
    monkeypatch, tmp_path
) -> None:
    solver = _solver(_model(), tmp_path)
    solver.full_path = str(tmp_path)
    solver.model_name = "nwt"
    seen: dict = {}
    descent = SimpleNamespace(without_adjacency=lambda: "bare")

    def fake_exits(rasters, exits, **kwargs):
        seen["rasters"] = rasters
        seen["exits"] = (exits, kwargs)
        return "exits"

    def fake_descent(solver_mesh, **kwargs):
        seen["descent"] = kwargs
        return descent

    def fake_basin(catchment, solver_mesh, found):
        seen["basin"] = (catchment, found)
        return "basin"

    monkeypatch.setattr(nwt_solver, "channel_exits_for_build", fake_exits)
    monkeypatch.setattr(nwt_solver, "build_solver_mesh_descent", fake_descent)
    monkeypatch.setattr(nwt_solver, "run_basin", fake_basin)
    monkeypatch.setattr(nwt_solver, "write_descent_sidecar", lambda *a, **k: None)
    mesh = solver_mesh_from_structured_arrays(
        nrow=1, ncol=1, top=np.zeros((1, 1)), botm=np.full((1, 1, 1), -1.0)
    )
    inputs = SimpleNamespace(ibound=np.ones((1, 1, 1)), chd_spd=None)

    result = solver._build_descent(mesh, inputs)

    catchment = solver.inputs.geometry.catchment
    assert seen["rasters"] is CHANNEL
    # NWT has no SFR, so A is never required, and the exits are those of the Model.
    assert seen["exits"] == (solver.inputs.geometry.channel_exits, {})
    assert seen["descent"]["channel_exits"] == "exits"
    assert seen["descent"]["geographic"] is catchment
    assert seen["basin"] == (catchment, descent)
    assert (result, solver.descent_basin) == ("bare", "basin")


@pytest.mark.parametrize(
    ("regime", "initial", "runs_the_auxiliary"),
    [
        ("transient", SteadyStart(), True),
        ("transient", HeadRule("top"), False),
        ("transient", CyclicStart(), False),
        ("steady", SteadyStart(), False),
    ],
    ids=["transient_steady_start", "transient_head_rule", "transient_cyclic", "steady_regime"],
)
def test_the_steady_initialization_runs_for_a_transient_run_with_a_steady_start(
    monkeypatch, tmp_path, regime, initial, runs_the_auxiliary
) -> None:
    solver = _solver(
        _model(
            initial=initial,
            time=ModelTime(grid=time_grid(1.0, 1.0), regime=regime, first_period_steady=False),
        ),
        tmp_path,
    )
    solver.flow_regime = regime
    solver.nper = 2
    solver.mf = _written_by(tmp_path)
    solver.bas = SimpleNamespace(strt=None, write_file=lambda: None)
    solver._params = SimpleNamespace(runtime=SimpleNamespace(lmt=None))
    head = np.full((1, 2, 3), 7.0)
    calls: list[str] = []
    monkeypatch.setattr(
        nwt_solver,
        "run_nwt_steady_state_initialization",
        lambda found: calls.append("run") or head,
    )
    monkeypatch.setattr(
        nwt_solver,
        "apply_nwt_steady_state_initial_heads",
        lambda found, value: calls.append("apply"),
    )
    monkeypatch.setattr(nwt_solver, "run_model_with_progress", lambda *args, **kwargs: (True, None))

    solver.processing(ModflowRunOptions(write_model=True, run_model=True))

    assert calls == (["run", "apply"] if runs_the_auxiliary else [])


def _written_by(tmp_path, *, files: tuple[str, ...] = ("n.nam", "n.dis", "n.bas")):
    """A FloPy model whose ``write_input`` writes ``files``; its packages declare ``n.dis`` twice."""

    def write_input() -> None:
        for name in files:
            (tmp_path / name).write_text(name)

    packages = [
        SimpleNamespace(file_name=["n.dis"]),
        SimpleNamespace(file_name=["n.bas", "n.dis"]),
        SimpleNamespace(file_name=["n.never_written"]),
    ]
    return SimpleNamespace(
        write_input=write_input,
        exe_name="mfnwt",
        namefile="n.nam",
        model_ws=str(tmp_path),
        packagelist=packages,
    )


def _processing_solver(monkeypatch, tmp_path):
    solver = _solver(
        _model(time=ModelTime(grid=time_grid(1.0), regime="transient", first_period_steady=False)),
        tmp_path,
    )
    solver.flow_regime = "transient"
    solver.nper = 1
    solver.mf = _written_by(tmp_path)
    solver._params = SimpleNamespace(runtime=SimpleNamespace(lmt=None))
    monkeypatch.setattr(nwt_solver, "run_model_with_progress", lambda *args, **kwargs: (True, None))
    return solver


def test_the_files_written_before_the_solve_are_listed_in_the_order_of_the_name_file(
    monkeypatch, tmp_path
) -> None:
    solver = _processing_solver(monkeypatch, tmp_path)

    assert solver.input_files == ()
    solver.processing(ModflowRunOptions(write_model=True, run_model=True))

    assert solver.input_files == ("n.nam", "n.dis", "n.bas")


def test_a_model_whose_files_are_written_writes_none_and_keeps_its_list(
    monkeypatch, tmp_path
) -> None:
    solver = _processing_solver(monkeypatch, tmp_path)
    solver.processing(ModflowRunOptions(write_model=True, run_model=False))
    (tmp_path / "n.dis").unlink()

    solver.processing(ModflowRunOptions(write_model=False, run_model=True))

    assert not (tmp_path / "n.dis").exists(), "nothing was written again"
    assert solver.input_files == ("n.nam", "n.dis", "n.bas")


class _Auxiliary:
    """Stands for the ``ModflowNwt`` the steady initialization builds."""

    built: list[_Auxiliary] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.model_name = kwargs["model_name"]
        self.full_path = kwargs["model_folder"]
        self.auxiliary = False
        self.inputs_given = None
        type(self).built.append(self)

    def pre_processing(self, model, options=None, **kwargs) -> None:
        self.inputs_given = model
        self.options_given = options
        self.extra = kwargs

    def processing(self, options) -> bool:
        return True


def _main_solver(tmp_path, model: Model) -> _Auxiliary:
    main = _Auxiliary(
        model_folder=str(tmp_path),
        model_name="main",
        modflow_config="config",
        bin_path="bin",
        preprocess_options=ModflowPreprocessOptions(
            box=False,
            sink_fill=True,
            drain_band_depth_m=0.5,
            drain_bed_thickness_m=2.0,
            drain_conductance_floor_m2_s=1e-9,
            check_grid=False,
            time_grid=model.time.grid,
        ),
    )
    main.exe = str(tmp_path / "bin" / "mfnwt")
    main.modflow_config = "config"
    main.preprocess_options = main.kwargs["preprocess_options"]
    main.inputs = model
    main.nlay, main.nrow, main.ncol = 1, 2, 3
    _Auxiliary.built.clear()
    return main


def test_the_auxiliary_solve_runs_on_the_steady_variant_and_keeps_the_model(
    monkeypatch, tmp_path
) -> None:
    recharge = FlowRechargeConfig(values={0: 0.1, 1: 0.3}, units="m/s")
    model = _model(
        recharge=recharge,
        active_sinks_sources=("recharge",),
        initial=SteadyStart(SteadyStateStrategy(source="mean_recharge")),
        time=ModelTime(grid=time_grid(1.0, 3.0), regime="transient", first_period_steady=False),
    )
    main = _main_solver(tmp_path, model)
    monkeypatch.setattr(
        steady_initial_conditions,
        "_read_final_head",
        lambda path, *, nlay, nrow, ncol: np.full((nlay, nrow, ncol), 4.0),
    )

    head = steady_initial_conditions.run_nwt_steady_state_initialization(main)

    (auxiliary,) = _Auxiliary.built
    steady = auxiliary.inputs_given
    options = auxiliary.kwargs["preprocess_options"]
    assert auxiliary.auxiliary is True
    assert auxiliary.model_name == "main_steady_ic"
    assert steady is not model
    assert (steady.time.regime, steady.initial) == ("steady", HeadRule("top"))
    assert steady.recharge.first_clim == "mean"
    assert steady.geometry is model.geometry
    assert options.time_grid is steady.time.grid
    assert list(steady.time.grid.period_lengths_seconds) == [4.0 * 86400.0]
    assert (options.box, options.sink_fill, options.drain_band_depth_m) == (False, True, 0.5)
    assert (options.drain_bed_thickness_m, options.drain_conductance_floor_m2_s) == (2.0, 1e-9)
    assert options.check_grid is False
    np.testing.assert_array_equal(head, np.full((1, 2, 3), 4.0))
    assert np.load(tmp_path / "_steady_state_initial_conditions.npz")["head_m"].mean() == 4.0
    # The model of the run is as it was.
    assert (model.time.regime, model.recharge.first_clim) == ("transient", recharge.first_clim)
    assert isinstance(model.initial, SteadyStart)


def test_the_steady_heads_are_set_in_the_bas_package_as_a_copy() -> None:
    solver = SimpleNamespace(nlay=1, nrow=2, ncol=3, bas=SimpleNamespace(strt=None))
    head = np.arange(6.0).reshape(1, 2, 3)

    steady_initial_conditions.apply_nwt_steady_state_initial_heads(solver, head)

    np.testing.assert_array_equal(solver.bas.strt, head)
    assert solver.bas.strt is not head
    assert solver._steady_state_initialization_solver == "modflow_nwt"


def _island_model(**members) -> Model:
    """A 4 by 5 model with a real domain and cell mesh, which ``pre_processing`` can build."""
    dem = np.linspace(20.0, 30.0, 20).reshape(4, 5)
    domain = _build_domain_from_dem(dem)
    geographic = _DummyGeographic(dem)
    geographic.crs_proj = "EPSG:2154"
    geometry = Geometry(
        cells=regular_cell_mesh_of_surface(domain.surface_topo, nrow=4, ncol=5),
        domain=domain,
        raster=RasterGeometry.from_geographic(geographic),
        catchment=CatchmentGeometry.from_geographic(geographic, crs="EPSG:2154"),
    )
    profiles = {
        "K": FieldParam(identifier="K", kind="homogeneous", value=1e-5),
        "Sy": FieldParam(identifier="Sy", kind="homogeneous", value=0.1),
        "Ss": FieldParam(identifier="Ss", kind="homogeneous", value=1e-5),
    }
    return make_model(
        geometry=geometry,
        properties=Properties(profiles=profiles),
        active_sinks_sources=("recharge",),
        **members,
    )


def test_pre_processing_builds_the_packages_from_the_model_and_keeps_it(tmp_path) -> None:
    model = _island_model(
        recharge=FlowRechargeConfig(values=1e-8, units="m/s"),
        time=ModelTime(grid=time_grid(1.0), regime="steady", first_period_steady=True),
    )
    solver = ModflowNwt(model_folder=str(tmp_path), model_name="island")

    solver.pre_processing(model, build_preprocess_options(model))

    assert solver.inputs is model
    assert (solver.nlay, solver.nrow, solver.ncol) == (1, 4, 5)
    assert (solver.xul, solver.yul) == (0.0, 4.0)
    assert solver.dem_watershed_path.endswith("_solver_grid_template.tif")
    assert solver.rch is not None
    assert solver.descent is not None
    np.testing.assert_allclose(solver.hk_value, 1e-5, rtol=1e-6)


def test_the_auxiliary_model_of_a_steady_start_is_steady_with_the_mean_recharge(
    monkeypatch, tmp_path
) -> None:
    model = _island_model(
        recharge=FlowRechargeConfig(values=[1e-8, 3e-8], units="m/s"),
        initial=SteadyStart(),
        time=ModelTime(grid=time_grid(1.0, 3.0), regime="transient", first_period_steady=False),
    )
    main = ModflowNwt(
        model_folder=str(tmp_path),
        model_name="main",
        preprocess_options=build_preprocess_options(model),
    )
    main.pre_processing(model)
    built: list[ModflowNwt] = []
    monkeypatch.setattr(
        ModflowNwt, "processing", lambda self, options=None: built.append(self) or True
    )
    monkeypatch.setattr(
        steady_initial_conditions,
        "_read_final_head",
        lambda path, *, nlay, nrow, ncol: np.full((nlay, nrow, ncol), 5.0),
    )

    steady_initial_conditions.run_nwt_steady_state_initialization(main)

    (auxiliary,) = built
    own_rates = [main.rch.rech[kper].array.mean() for kper in (0, 1)]
    assert own_rates == pytest.approx([1e-8, 3e-8], rel=1e-5)
    assert main.steady.tolist() == [False, False]
    assert auxiliary.steady.tolist() == [True]
    assert auxiliary.nper == 1
    # The duration-weighted mean of the two rates, over 1 and 3 days.
    assert auxiliary.rch.rech[0].array.mean() == pytest.approx(2.5e-8, rel=1e-5)
    assert auxiliary.descent is None
    # The auxiliary solve starts from the top, in single precision like FloPy.
    np.testing.assert_allclose(auxiliary.bas.strt.array[0], auxiliary.top_elevation, rtol=1e-6)
