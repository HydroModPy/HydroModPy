"""What the workflow does with the solver outputs of a run: extract, derive, cleanup.

Each function reads one ``RunContext`` whose ``solver_run`` the runner recorded.
The extract step hands the adapter of the backend that solver run and the
``Retention`` of the run, and nothing else. The adapter reads its own files.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import ConfigError, NothingThereError, SolverInputError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.model.forcing.recharge_rates import CRITERION_MEAN_RECHARGE_ATTR
from hydromodpy.model.model import ModelOptions
from hydromodpy.results.derive.stream_network.criterion_inputs import catchment_cells
from hydromodpy.results.storage.kept import Retention
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan, SolverRun
from hydromodpy.workflow.steps.run_outputs import (
    _keep_what_the_criterion_reads,
    cleanup_solver_outputs,
    derive_run_outputs,
    extract_run_outputs,
)
from tests._helpers.fake_solvers import fake_adapter
from tests._helpers.model_factory import make_model
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.solver.modflow_common.solver_runs import keep_all, retention, solved_run


class _Zarr:
    drain_band_depth_m = None

    def close(self) -> None:
        pass


class _Store:
    """The open store of a run: it names its run and opens a field store."""

    sim_id = "sim-12345678"
    project_path = Path(".")
    run_dir = Path("no-run-dir-on-disk")

    def __init__(self) -> None:
        self.zarr = _Zarr()

    def open_zarr(self, _sim_id: str) -> _Zarr:
        return self.zarr


class _Seen:
    """What the adapter registered by one test received."""

    def __init__(self) -> None:
        self.extracted: list[tuple[SolverRun, Any, Retention]] = []
        self.cleaned: list[SolverRun] = []


def _install(monkeypatch, isolated_solvers, *, category: str = "distributed") -> _Seen:
    """Register ``flow_fake_solver`` with an adapter that records its calls, and stub the rest."""
    seen = _Seen()

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        seen.extracted.append((solver_run, store, retention))

    def cleanup(self, solver_run: SolverRun) -> None:
        seen.cleaned.append(solver_run)
        shutil.rmtree(solver_run.output_dir)

    isolated_solvers.solvers.register(
        fake_adapter("fake_solver", category=category, extract=extract, cleanup=cleanup)
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.run_outputs._finalize_run_provenance", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.run_outputs._keep_what_the_criterion_reads",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.results.derive.catchment_aggregation.aggregate_catchment_timeseries",
        lambda sim_id, store, **kwargs: None,
    )
    return seen


def _context(
    solver_name: str = "fake_solver",
    *,
    process_type: str = "flow",
    solver_run: SolverRun | None = None,
) -> RunContext:
    run = ProcessRun(
        id=f"{process_type}_main::{solver_name}",
        process_id=f"{process_type}_main",
        process_type=process_type,
        solver=solver_name,
    )
    plan = SimulationPlan(name="test", description="test", runs=(run,))
    return RunContext(
        plan=plan, run=run, state=RunState(cfg=SimpleNamespace()), solver_run=solver_run
    )


def _solved_in(tmp_path: Path, **members: Any) -> SolverRun:
    solver_dir = tmp_path / "solver_out"
    solver_dir.mkdir()
    (solver_dir / "model.hds").write_text("head data")
    return solved_run(solver_dir, **members)


def test_the_adapter_receives_the_solver_run_and_the_retention_untouched(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    solver_run = _solved_in(tmp_path)
    planned = retention(BudgetKeep.of_terms(("drain",)))
    store = _Store()

    extract_run_outputs(ctx=_context(solver_run=solver_run), store=store, retention=planned)

    assert len(seen.extracted) == 1
    got_run, got_store, got_retention = seen.extracted[0]
    assert got_run is solver_run and got_store is store and got_retention is planned


def test_a_run_that_is_not_solver_backed_extracts_nothing(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    ctx = _context("catchment", process_type="mesh", solver_run=_solved_in(tmp_path))

    extract_run_outputs(ctx=ctx, store=_Store(), retention=keep_all)

    assert seen.extracted == []


def test_an_unknown_solver_is_refused_by_its_registry(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    _install(monkeypatch, isolated_solvers)
    ctx = _context("custom_solver", solver_run=_solved_in(tmp_path))

    with pytest.raises(SolverInputError):
        extract_run_outputs(ctx=ctx, store=_Store(), retention=keep_all)


@pytest.mark.parametrize("case", ["no solver run", "no output folder", "a folder that is gone"])
def test_a_run_without_its_output_folder_is_nothing_there(
    case: str, tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    slot = RunSlot(tmp_path, "island")
    solver_run = {
        "no solver run": None,
        "no output folder": SolverRun(slot=slot),
        "a folder that is gone": solved_run(tmp_path / "gone"),
    }[case]

    with pytest.raises(NothingThereError, match="Solver output directory is missing"):
        extract_run_outputs(ctx=_context(solver_run=solver_run), store=_Store(), retention=keep_all)
    assert seen.extracted == []


def test_the_solver_files_go_when_the_run_does_not_keep_them(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    solver_run = _solved_in(tmp_path)

    cleanup_solver_outputs(
        ctx=_context(solver_run=solver_run), retention=retention(solver_files=False)
    )

    assert not solver_run.output_dir.exists()
    assert seen.cleaned == [solver_run]


def test_the_solver_files_stay_when_the_run_keeps_them(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    solver_run = _solved_in(tmp_path)

    cleanup_solver_outputs(
        ctx=_context(solver_run=solver_run), retention=retention(solver_files=True)
    )

    assert (solver_run.output_dir / "model.hds").exists()
    assert seen.cleaned == []


def test_a_run_with_no_solver_run_has_nothing_to_clean(monkeypatch, isolated_solvers) -> None:
    seen = _install(monkeypatch, isolated_solvers)

    cleanup_solver_outputs(ctx=_context(), retention=keep_all)

    assert seen.cleaned == []


def test_a_failing_cleanup_is_logged_and_does_not_stop_the_run(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    def cleanup(self, solver_run: SolverRun) -> None:
        raise OSError("locked")

    isolated_solvers.solvers.register(fake_adapter("fake_solver", cleanup=cleanup))

    cleanup_solver_outputs(ctx=_context(solver_run=_solved_in(tmp_path)), retention=keep_all)


def _derived(*, model: Any) -> RunContext:
    return _context(solver_run=SolverRun(slot=RunSlot(Path("scratch"), "island"), model=model))


def test_derive_writes_the_drain_band_of_the_model(monkeypatch, isolated_solvers) -> None:
    _install(monkeypatch, isolated_solvers)
    store = _Store()
    model = make_model(
        options=ModelOptions(
            sink_fill=False,
            drain_band_depth_m=2.5,
            drain_bed_thickness_m=1.0,
            drain_conductance_floor_m2_s=1e-12,
        )
    )

    derive_run_outputs(ctx=_derived(model=model), store=store)

    assert store.zarr.drain_band_depth_m == 2.5


def test_a_distributed_backend_aggregates_the_catchment(monkeypatch, isolated_solvers) -> None:
    _install(monkeypatch, isolated_solvers)
    calls: list[dict] = []
    monkeypatch.setattr(
        "hydromodpy.results.derive.catchment_aggregation.aggregate_catchment_timeseries",
        lambda sim_id, store, **kwargs: calls.append({"sim_id": sim_id, **kwargs}),
    )

    derive_run_outputs(ctx=_derived(model=make_model()), store=_Store())

    assert [call["sim_id"] for call in calls] == ["sim-12345678"]
    assert calls[0]["drainage_outside_routed"] is True, "a model without a network routes nothing"


def test_a_lumped_backend_skips_catchment_aggregation(monkeypatch, isolated_solvers) -> None:
    _install(monkeypatch, isolated_solvers, category="lumped")

    def fail(sim_id, store, **kwargs):
        raise AssertionError("lumped extractors must not aggregate spatial fields")

    monkeypatch.setattr(
        "hydromodpy.results.derive.catchment_aggregation.aggregate_catchment_timeseries", fail
    )

    derive_run_outputs(ctx=_derived(model=make_model()), store=_Store())


@pytest.mark.parametrize("case", ["no solver run", "a solver run without a Model"])
def test_a_run_without_a_model_cannot_be_derived(case: str, monkeypatch, isolated_solvers) -> None:
    _install(monkeypatch, isolated_solvers)
    ctx = _context() if case == "no solver run" else _derived(model=None)

    with pytest.raises(ConfigError, match="no Model to derive from"):
        derive_run_outputs(ctx=ctx, store=_Store())


# The run keeps what the stream criterion read: the mean recharge, the cells of open
# water and the cells inside the catchment outline. The functions are the ones a trial
# calls, so a figure redrawn from the store scores what the trials scored.
CRS = "EPSG:2154"
GRID_ROWS, GRID_COLUMNS, CELL_M = 3, 4, 100.0
N_GRID_CELLS = GRID_ROWS * GRID_COLUMNS


class _KeptStore:
    """The open store of a run whose field store holds a mesh of twelve cells."""

    sim_id = "sim-12345678"
    save_zarr = True

    def __init__(self, tmp_path: Path) -> None:
        self.path = tmp_path / "fields.zarr"
        self.fields_path = self.path
        self.facts = SimpleNamespace(period_start=None)
        SimulationZarr.create(self.path, n_cells=N_GRID_CELLS, n_layers=1).close()
        vertices, faces = quad_mesh(GRID_ROWS, GRID_COLUMNS, cell_size=CELL_M)
        with SimulationZarr(self.path) as fields:
            fields.write_mesh(vertices, faces, np.zeros((2, N_GRID_CELLS)))

    def open_zarr(self, _sim_id: str) -> SimulationZarr:
        return SimulationZarr(self.path)

    def stored(self, name: str) -> np.ndarray | None:
        with SimulationZarr(self.path) as fields:
            mesh = fields.root["mesh"]
            return None if name not in mesh else np.asarray(mesh[name][:])


def _kept_context(tmp_path: Path, *, lake=None, outline: bool = True, lumped: bool = False):
    vertices, faces = quad_mesh(GRID_ROWS, GRID_COLUMNS, cell_size=CELL_M)
    shp = None
    if outline:
        shp = tmp_path / "watershed.gpkg"
        gpd.GeoDataFrame(geometry=[box(0.0, 0.0, 2 * CELL_M, GRID_ROWS * CELL_M)], crs=CRS).to_file(
            shp, driver="GPKG"
        )
    mesh = SimpleNamespace(
        n_cells=N_GRID_CELLS,
        planar_mesh=SimpleNamespace(vertices=vertices, flat_connectivity=faces),
        cell_areas=lambda: np.full(N_GRID_CELLS, CELL_M * CELL_M),
    )
    model = SimpleNamespace(
        recharge=pd.Series([2.0e-8]),
        open_water_cell_ids=lake,
        **({} if lumped else {"solver_mesh": mesh}),
    )
    geographic = SimpleNamespace(watershed_shp=shp, crs_project=CRS)
    context = _context(
        solver_run=SolverRun(slot=RunSlot(Path("scratch"), "island"), solver_model=model)
    )
    context.state.setup.geographic = geographic
    return context, geographic, vertices, faces


def test_the_run_keeps_the_open_water_the_outline_and_the_recharge_its_trials_read(
    tmp_path,
) -> None:
    store = _KeptStore(tmp_path)
    ctx, geographic, vertices, faces = _kept_context(tmp_path, lake=[3, 4, 99])

    _keep_what_the_criterion_reads(ctx=ctx, sim_id=store.sim_id, store=store)

    assert np.flatnonzero(store.stored("open_water")).tolist() == [3, 4]
    outline = gpd.read_file(geographic.watershed_shp)
    expected = catchment_cells(cell_polygons(vertices, faces), outline, mesh_crs=CRS)
    assert expected.any() and not expected.all()
    np.testing.assert_array_equal(store.stored("catchment_cells"), expected)
    with SimulationZarr(store.path) as fields:
        kept = fields.root["forcing"].attrs[CRITERION_MEAN_RECHARGE_ATTR]
    assert kept == pytest.approx(2.0e-8)


def test_a_run_without_an_outline_keeps_no_catchment_cells(tmp_path) -> None:
    store = _KeptStore(tmp_path)
    ctx, *_ = _kept_context(tmp_path, outline=False)

    _keep_what_the_criterion_reads(ctx=ctx, sim_id=store.sim_id, store=store)

    assert store.stored("open_water") is not None
    assert store.stored("catchment_cells") is None


def test_a_run_with_no_cell_mesh_keeps_no_cell_mask(tmp_path) -> None:
    store = _KeptStore(tmp_path)
    ctx, *_ = _kept_context(tmp_path, lumped=True)

    _keep_what_the_criterion_reads(ctx=ctx, sim_id=store.sim_id, store=store)

    assert store.stored("open_water") is None
    assert store.stored("catchment_cells") is None


def test_a_run_without_a_model_keeps_nothing(tmp_path) -> None:
    store = _KeptStore(tmp_path)

    _keep_what_the_criterion_reads(ctx=_context(), sim_id=store.sim_id, store=store)

    assert store.stored("open_water") is None


def _kept_recharge(store: _KeptStore) -> Any:
    with SimulationZarr(store.path) as fields:
        return fields.root["forcing"].attrs.get(CRITERION_MEAN_RECHARGE_ATTR)


def test_a_transport_run_of_the_same_store_leaves_the_kept_recharge_intact(tmp_path) -> None:
    store = _KeptStore(tmp_path)
    flow, *_ = _kept_context(tmp_path, lake=[3])
    _keep_what_the_criterion_reads(ctx=flow, sim_id=store.sim_id, store=store)
    transport = _context(
        process_type="transport",
        solver_run=SolverRun(slot=RunSlot(Path("scratch"), "island"), solver_model=object()),
    )

    _keep_what_the_criterion_reads(ctx=transport, sim_id=store.sim_id, store=store)

    assert _kept_recharge(store) == pytest.approx(2.0e-8)
    assert np.flatnonzero(store.stored("open_water")).tolist() == [3]


@pytest.mark.parametrize("case", ["no_field_store", "save_zarr_off"])
def test_a_run_that_keeps_no_field_store_gains_none(case: str, tmp_path) -> None:
    opened: list[str] = []
    store = SimpleNamespace(
        sim_id="sim-12345678",
        save_zarr=case != "save_zarr_off",
        fields_path=tmp_path / "fields.zarr",
        open_zarr=opened.append,
    )
    if case == "save_zarr_off":
        store.fields_path.mkdir()
    ctx, *_ = _kept_context(tmp_path)

    _keep_what_the_criterion_reads(ctx=ctx, sim_id=store.sim_id, store=store)

    assert opened == []
