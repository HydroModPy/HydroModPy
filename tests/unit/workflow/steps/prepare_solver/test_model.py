"""``step_build_model`` freezes the ``Flow`` of a run into the ``Model`` its solver reads, and cuts it per window.

The mesh is 2 x 3 cells of 100 m. The step runs in the persisted branch, in the branch of a
calibration trial that writes nothing, and again on a resume. A hotstart named by a run is
resolved in all three, and one solved on another mesh is refused before the solve. A window of
a chain is cut from the ``Model`` of the whole simulation, one value per stress period (30 days).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rasterio
import zarr
from rasterio.transform import from_origin

import hydromodpy.workflow.steps.prepare_solver.step as step_module
from hydromodpy.core.exceptions import ConfigError, IncompatibleMeshError
from hydromodpy.core.state.run_state import ExecutionRegistry, SetupContext
from hydromodpy.core.time.window import ChainWindow
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.forcing.native import NativeSeries
from hydromodpy.model.initial.state import (
    CyclicStart,
    HeadRule,
    PriorState,
    SteadyStart,
)
from hydromodpy.model.model import Model, ModelTime
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.prepare_solver.model import (
    cut_native,
    cut_periods,
    step_build_model,
    window_model,
)
from hydromodpy.workflow.steps.prepare_solver.step import PrepareSolverStep
from tests._helpers.model_factory import make_model, time_grid
from tests._helpers.regular_cell_meshes import regular_cell_mesh
from tests._helpers.sealed_runs import write_attempt
from tests.unit.workflow.steps.prepare_solver._helpers import sealed_run

XMIN, YMIN = 350_000.0, 6_800_000.0


def mesh():
    return regular_cell_mesh(xmin=XMIN, ymin=YMIN, dx=100.0, dy=100.0, nrow=2, ncol=3)


def ctx_of(project: Path, *, restart_from=None, with_mesh=True, geographic=None, traces=None):
    config = FlowConfig(restart_from=restart_from)
    cfg = SimpleNamespace(
        flow=config,
        solver=SolverConfig(),
        geographic=SimpleNamespace(crs_project="EPSG:2154"),
        simulation=SimpleNamespace(),
    )
    setup = SimpleNamespace(
        flow=Flow(config=config),
        cell_mesh=mesh() if with_mesh else None,
        domain=None,
        geographic=geographic,
        time_grid=None,
        flow_runtime_overrides=None,
        workspace=SimpleNamespace(project_root=project),
        products={},
        model=None,
        sfr_reach_traces=traces,
    )
    return SimpleNamespace(cfg=cfg, setup=setup, execution=ExecutionRegistry(lightweight=True))


def write_prior(store: Path, *, mesh=None, moved: float = 0.0) -> None:
    """Write the ``head`` field of an earlier run, with the mesh of ``mesh`` when given."""
    root = zarr.open(str(store), mode="w")
    root.attrs["zarr_schema_version"] = str(ZARR_SCHEMA_VERSION)
    root["head"] = np.arange(6, dtype=float).reshape(1, 1, 6)
    if mesh is not None:
        xy = mesh.mesh.vertices[:, :2].copy()
        xy[0, 0] += moved
        group = root.create_group("mesh")
        group["vertices"] = np.column_stack([xy, np.zeros(len(xy))])
        group["face_node_connectivity"] = mesh.geometry.padded_connectivity.astype("int32")


def test_setup_members() -> None:
    # A per-cell property is ``Model.with_properties``: the setup has no dictionary to hold one.
    members = {member.name for member in dataclasses.fields(SetupContext)}

    assert "slot_request" in members
    assert "flow_runtime_overrides" not in members


def test_hotstart_naming_no_run_is_refused(tmp_path: Path) -> None:
    ctx = ctx_of(tmp_path, restart_from="nowhere")

    with pytest.raises(ConfigError, match="names no field store"):
        step_build_model(ctx)


HOTSTART_REFUSALS = [
    pytest.param(
        {"mesh": mesh(), "moved": 0.5}, True, IncompatibleMeshError, "another mesh", id="other mesh"
    ),
    pytest.param({}, False, ConfigError, "cell mesh", id="no cell mesh"),
]


@pytest.mark.parametrize(("prior", "with_mesh", "error", "match"), HOTSTART_REFUSALS)
def test_hotstart_refusals(tmp_path: Path, prior, with_mesh, error, match) -> None:
    store = tmp_path / "prior.zarr"
    write_prior(store, **prior)
    ctx = ctx_of(tmp_path, restart_from=str(store), with_mesh=with_mesh)

    with pytest.raises(error, match=match):
        step_build_model(ctx)
    assert ctx.setup.model is None


LINK = "dem_stream_link_id_full.tif"
POINTER = "dem_direc.tif"
ACCUMULATION = "dem_acc_cells.tif"
EAST = 2  # the WhiteboxTools D8 code of a step to the east


def write_raster(path: Path, data: np.ndarray) -> None:
    # The raster is the mesh (2 x 3 cells of 100 m) with one pixel of margin around it.
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        transform=from_origin(XMIN - 100.0, YMIN + 300.0, 100.0, 100.0),
    ) as dst:
        dst.write(data, 1)


def write_network(folder: Path) -> None:
    # A along raster row 1, columns 1 to 3: the three cells of the north row of the mesh.
    link = np.zeros((4, 5), dtype=np.int32)
    link[1, 1:4] = 1
    write_raster(folder / LINK, link)
    write_raster(folder / POINTER, np.full((4, 5), EAST, dtype=np.int32))
    write_raster(folder / ACCUMULATION, np.arange(20, dtype=np.float32).reshape(4, 5))


def geographic_of(folder: Path | None, *, enabled: bool = True, **clipped: object):
    return SimpleNamespace(
        correcflow_path=None if folder is None else str(folder),
        river_network_enabled=enabled,
        **clipped,
    )


def exits_of(project: Path, geographic, *, traces=None):
    ctx = ctx_of(project, geographic=geographic, traces=traces)
    return step_build_model(ctx).geometry.channel_exits


@pytest.mark.parametrize("traces", [None, {"net0": object()}], ids=["no traces", "traces"])
def test_network_on_mesh_cells(tmp_path: Path, traces) -> None:
    write_network(tmp_path)

    exits = exits_of(tmp_path, geographic_of(tmp_path), traces=traces)

    assert exits is not None and exits.n_cells == 6
    assert np.flatnonzero(exits.holds_a).tolist() == [0, 1, 2]
    assert exits.next_cell[:3].tolist() == [1, 2, -1]
    assert exits.next_on_a[:3].tolist() == [True, True, False]


def test_sfr_network_with_step_off(tmp_path: Path) -> None:
    write_network(tmp_path)

    exits = exits_of(tmp_path, geographic_of(tmp_path, enabled=False), traces={"net0": object()})

    assert exits is not None and exits.holds_a.sum() == 3


@pytest.mark.parametrize("traces", [None, {}], ids=["none", "empty"])
def test_old_rasters_not_read(tmp_path: Path, traces) -> None:
    write_network(tmp_path)

    assert exits_of(tmp_path, geographic_of(tmp_path, enabled=False), traces=traces) is None


def test_missing_rasters_no_exits(tmp_path: Path) -> None:
    assert exits_of(tmp_path, geographic_of(tmp_path), traces={"net0": object()}) is None


def test_clipped_rasters_are_never_the_network(tmp_path: Path) -> None:
    clipped = tmp_path / "clipped.tif"
    write_raster(clipped, np.ones((4, 5), dtype=np.int32))
    geographic = geographic_of(None, river_streams_tif=str(clipped))

    assert exits_of(tmp_path, geographic, traces={"net0": object()}) is None


def test_tree_off_the_mesh(tmp_path: Path) -> None:
    write_network(tmp_path)
    write_raster(tmp_path / LINK, np.zeros((4, 5), dtype=np.int32))

    exits = exits_of(tmp_path, geographic_of(tmp_path))

    assert exits is not None and exits.n_cells == 6 and not exits.holds_a.any()


# The persisted branch builds the model after the run is open and writes the profiles from it.
# A trial that writes nothing builds it too. A resume builds it again, so that a run resumed at
# run_solver finds one.


class FakeStore:
    def __init__(self, calls: list) -> None:
        self.calls = calls
        self.facts = SimpleNamespace()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def quiet(monkeypatch, calls: list, ctx) -> None:
    # Replace what the step writes on disk by records of the order of the calls.
    store = FakeStore(calls)
    monkeypatch.setattr(
        step_module, "_resolve_plan_and_results", lambda c, lineage=None, store=None: None
    )
    monkeypatch.setattr(step_module, "bind_run_directory", lambda *a, **k: None)
    monkeypatch.setattr(step_module, "initial_facts", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(step_module.RunStore, "open", lambda *a, **k: store)
    monkeypatch.setattr(step_module, "run_store", lambda c: store)
    monkeypatch.setattr(
        step_module, "step_open_run", lambda c, store: calls.append(("open", c.setup.model))
    )
    monkeypatch.setattr(step_module, "step_write_provenance", lambda c, store: None)
    monkeypatch.setattr(step_module, "step_persist_forcings", lambda c, store: None)
    monkeypatch.setattr(
        step_module,
        "step_persist_params",
        lambda store, sim_id, profiles, *, domain=None: calls.append(("params", profiles, domain)),
    )
    ctx.sim_id = "sim-1"
    ctx.run_dir = Path(".")


def make_persisted(ctx) -> None:
    ctx.execution.lightweight = False
    ctx.cfg.simulation = SimpleNamespace(
        results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=True))
    )


def test_persisted_branch_model(tmp_path, monkeypatch) -> None:
    ctx = ctx_of(tmp_path)
    make_persisted(ctx)
    ctx.setup.model = "built for an earlier run"
    calls: list = []
    quiet(monkeypatch, calls, ctx)
    state = PipelineState(run_id="run", data={"ctx": ctx})

    PrepareSolverStep().run(state)

    assert isinstance(ctx.setup.model, Model)
    assert calls[0] == ("open", None)
    kind, profiles, domain = calls[1]
    assert kind == "params"
    assert profiles is ctx.setup.model.properties.profiles
    assert domain is None


def test_trial_builds_model(tmp_path, monkeypatch) -> None:
    ctx = ctx_of(tmp_path)
    calls: list = []
    quiet(monkeypatch, calls, ctx)

    PrepareSolverStep().run(PipelineState(run_id="run", data={"ctx": ctx}))

    assert isinstance(ctx.setup.model, Model)
    assert calls == []


@pytest.mark.parametrize("persisted", [False, True], ids=["not persisted", "persisted"])
def test_resume_builds_the_model_again(tmp_path, monkeypatch, persisted: bool) -> None:
    sealed_run(tmp_path, "first")
    write_prior(tmp_path / "runs" / "first" / FIELDS_STORE_NAME, mesh=mesh())
    ctx = ctx_of(tmp_path, restart_from="first")
    calls: list = []
    quiet(monkeypatch, calls, ctx)
    data = {"ctx": ctx}
    if persisted:
        make_persisted(ctx)
        data["run_dir"] = write_attempt(tmp_path, "runs/run", status="failed", sim_id="sim-1")
    prior = PipelineState(run_id="run", step_index=5, data=data)

    PrepareSolverStep().rebuild_state(prior_state=prior, workspace=tmp_path, run_id="run")

    assert isinstance(ctx.setup.model, Model)
    assert isinstance(ctx.setup.model.initial, PriorState)


MONTHS = [pd.Timestamp(2020, month, 1) for month in range(1, 13)] + [pd.Timestamp(2021, 1, 1)]


def window_of(index: int, count: int = 2, *, first: int = 0, stop: int = 6) -> ChainWindow:
    return ChainWindow(
        index=index,
        count=count,
        first_period=first,
        stop_period=stop,
        start=MONTHS[first],
        end=MONTHS[stop],
    )


def whole_model(**members):
    return make_model(
        time=ModelTime(grid=time_grid(*[30.0] * 12), regime="transient", first_period_steady=True),
        **members,
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (list(range(12)), [6, 7, 8, 9, 10, 11]),
        (tuple(range(12)), (6, 7, 8, 9, 10, 11)),
        (list(range(5)), list(range(5))),
        (2.5e-9, 2.5e-9),
        ("mean", "mean"),
        (
            {period: float(period) for period in range(12)},
            {0: 6.0, 1: 7.0, 2: 8.0, 3: 9.0, 4: 10.0, 5: 11.0},
        ),
        ({"a": 1.0}, {"a": 1.0}),
        (None, None),
    ],
    ids=["list", "tuple", "other length", "scalar", "text", "period table", "other keys", "none"],
)
def test_cut_periods(values, expected) -> None:
    assert cut_periods(values, 6, 12, 12) == expected


def test_array_and_series_cut() -> None:
    array = cut_periods(np.arange(12.0), 6, 12, 12)
    series = cut_periods(pd.Series(np.arange(12.0)), 6, 12, 12)
    dated = cut_periods(pd.Series(np.arange(12.0), index=pd.DatetimeIndex(MONTHS[:12])), 6, 12, 12)

    assert array.tolist() == [6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    assert series.tolist() == array.tolist()
    assert list(series.index) == [0, 1, 2, 3, 4, 5], "a builder reads its periods from 0"
    assert dated.index[0] == MONTHS[6], "a dated series keeps its dates"


@pytest.mark.parametrize(
    ("shape", "cut_shape"),
    [((12, 4), (6, 4)), ((12, 2, 4), (6, 2, 4)), ((4, 12), (4, 12))],
    ids=["a map per period", "a map per layer and period", "periods on the second axis"],
)
def test_array_cut_on_first_axis(shape, cut_shape) -> None:
    values = np.arange(np.prod(shape), dtype=float).reshape(shape)

    cut = cut_periods(values, 6, 12, 12)

    assert cut.shape == cut_shape
    if cut_shape != shape:
        np.testing.assert_array_equal(cut, values[6:12])


def test_window_forcings_cut() -> None:
    whole = whole_model(
        recharge=FlowRechargeConfig(values=[float(i) for i in range(12)], units="m/s"),
        lakes={
            "L": {
                "stage": 3.0,
                "runoff_rate": {"kind": "values", "values": [float(i) for i in range(12)]},
                "outlet": {"kind": "constant", "value": 1.0},
            }
        },
        sfr={"S": {"runoff": {"kind": "values", "values": [1.0, 2.0, 3.0]}}},
        initial=HeadRule("top"),
    )
    grid = time_grid(*[30.0] * 6)

    window = window_model(whole, window_of(2, first=6, stop=12), grid=grid)

    assert window.recharge.values == [6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    assert window.lakes["L"]["runoff_rate"]["values"] == [6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    assert window.lakes["L"]["stage"] == 3.0
    assert window.lakes["L"]["outlet"] == {"kind": "constant", "value": 1.0}
    assert window.sfr["S"]["runoff"]["values"] == [1.0, 2.0, 3.0], "a length that is not nper stays"
    assert window.time.grid is grid
    assert whole.recharge.values == [float(i) for i in range(12)], "the whole model is untouched"
    assert whole.lakes["L"]["runoff_rate"]["values"] == [float(i) for i in range(12)]


def test_constant_forcing_shared() -> None:
    whole = whole_model(recharge=FlowRechargeConfig(values=2.0e-9, units="m/s"))
    window = window_model(whole, window_of(2, first=6, stop=12), grid=time_grid(*[30.0] * 6))
    assert window.recharge is whole.recharge


@pytest.mark.parametrize(
    ("initial", "index", "count", "keeps_whole"),
    [
        (SteadyStart(), 1, 2, True),
        (CyclicStart(), 1, 3, True),
        (SteadyStart(), 1, 1, False),
        (HeadRule("top"), 1, 2, False),
        (PriorState(head=np.zeros((1, 6)), lake_stages={}, path="p"), 1, 2, False),
    ],
    ids=["steady", "cyclic", "one window", "top", "prior state"],
)
def test_first_window_start(initial, index: int, count: int, keeps_whole: bool) -> None:
    whole = whole_model(initial=initial)

    window = window_model(
        whole, window_of(index, count, first=0, stop=6), grid=time_grid(*[30.0] * 6)
    )

    over = getattr(window.initial, "over", None)
    assert (over is whole) is keeps_whole
    if keeps_whole:
        assert len(over.time.grid.period_lengths_seconds) == 12
        assert whole.initial is initial, "the whole model starts without a whole model of its own"


def native_series() -> NativeSeries:
    return NativeSeries(starts=pd.DatetimeIndex(MONTHS), values=np.arange(12.0))


def test_native_recharge_cut() -> None:
    cut = cut_native(native_series(), window_of(2, first=6, stop=12))
    assert list(cut.starts) == MONTHS[6:13]
    assert cut.values.tolist() == [6.0, 7.0, 8.0, 9.0, 10.0, 11.0]


def test_native_recharge_off_edges() -> None:
    offset = NativeSeries(
        starts=pd.DatetimeIndex(MONTHS) + pd.Timedelta(3, unit="D"), values=np.arange(12.0)
    )
    assert cut_native(offset, window_of(2, first=6, stop=12)) is offset
    assert cut_native(None, window_of(2, first=6, stop=12)) is None
