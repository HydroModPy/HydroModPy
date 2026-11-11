"""``step_build_model`` freezes the ``Flow`` of a run into the ``Model`` its solver reads.

The step runs in the persisted branch, in the branch of a calibration trial that
writes nothing, and again on a resume. A hotstart named by a run is resolved in
all three, the earlier run is read once, and one that was solved on another mesh
is refused before the solve.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import zarr

import hydromodpy.workflow.steps.prepare_solver.model as model_module
import hydromodpy.workflow.steps.prepare_solver.step as step_module
from hydromodpy.core.exceptions import ConfigError, IncompatibleMeshError
from hydromodpy.core.state.run_state import ExecutionRegistry, SetupContext
from hydromodpy.model.domain.geometry import ChannelRasters
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial.state import HeadRule, PriorState
from hydromodpy.model.model import Model
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.prepare_solver.model import step_build_model
from hydromodpy.workflow.steps.prepare_solver.step import PrepareSolverStep
from tests._helpers.regular_cell_meshes import regular_cell_mesh
from tests.unit.workflow.steps.prepare_solver._helpers import sealed_run

_XMIN, _YMIN = 350_000.0, 6_800_000.0


def _mesh():
    return regular_cell_mesh(xmin=_XMIN, ymin=_YMIN, dx=100.0, dy=100.0, nrow=2, ncol=3)


def _ctx(project: Path, *, restart_from=None, mesh=True, geographic=None):
    config = FlowConfig(restart_from=restart_from)
    cfg = SimpleNamespace(
        flow=config,
        solver=SolverConfig(),
        geographic=SimpleNamespace(crs_project="EPSG:2154"),
        simulation=SimpleNamespace(),
    )
    setup = SimpleNamespace(
        flow=Flow(config=config),
        cell_mesh=_mesh() if mesh else None,
        domain=None,
        geographic=geographic,
        time_grid=None,
        workspace=SimpleNamespace(project_root=project),
        products={},
        model=None,
    )
    return SimpleNamespace(cfg=cfg, setup=setup, execution=ExecutionRegistry(lightweight=True))


def _write_prior(store: Path, *, mesh=None, head=None, moved: float = 0.0) -> None:
    """Write the ``head`` field of an earlier run, with the mesh of ``mesh`` when given."""
    root = zarr.open(str(store), mode="w")
    root.attrs["zarr_schema_version"] = str(ZARR_SCHEMA_VERSION)
    root["head"] = np.arange(6, dtype=float).reshape(1, 1, 6) if head is None else head
    if mesh is not None:
        xy = mesh.mesh.vertices[:, :2].copy()
        xy[0, 0] += moved
        group = root.create_group("mesh")
        group["vertices"] = np.column_stack([xy, np.zeros(len(xy))])
        group["face_node_connectivity"] = mesh.geometry.padded_connectivity.astype("int32")


def test_a_run_without_a_flow_has_no_model(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.setup.flow = None
    ctx.setup.model = "stale"

    assert step_build_model(ctx) is None
    assert ctx.setup.model is None


def test_the_model_is_put_on_the_setup_with_the_members_of_the_flow(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    model = step_build_model(ctx)

    assert isinstance(model, Model)
    assert ctx.setup.model is model
    assert model.geometry.cells is ctx.setup.cell_mesh
    assert dict(model.properties.profiles) == dict(ctx.setup.flow.parameters)
    assert model.initial == HeadRule("top")
    assert model.geometry.raster is None
    assert model.geometry.catchment is None


def test_the_river_rasters_are_chosen_once_for_the_run(tmp_path: Path, monkeypatch) -> None:
    geographic = SimpleNamespace(river_network_enabled=False, correcflow_path=None)
    calls = []
    chosen = ChannelRasters(enabled=False, link=None, pointer=None, accumulation=None)

    def fake(geo):
        calls.append(geo)
        return chosen

    monkeypatch.setattr(model_module, "channel_rasters_for_run", fake)
    ctx = _ctx(tmp_path, geographic=geographic)

    model = step_build_model(ctx)

    assert calls == [geographic]
    assert model.geometry.raster.channel is chosen
    assert model.geometry.channel_exits is None
    assert model.geometry.catchment.crs == "EPSG:2154"


def test_the_setup_carries_what_a_trial_asks_of_its_slot_and_no_property_envelope() -> None:
    """A per-cell property is ``Model.with_properties``: the setup has no dictionary to hold one."""
    members = {member.name for member in dataclasses.fields(SetupContext)}

    assert "slot_request" in members
    assert "flow_runtime_overrides" not in members


def test_a_hotstart_by_path_becomes_a_prior_state(tmp_path: Path) -> None:
    store = tmp_path / "prior.zarr"
    _write_prior(store, mesh=_mesh())
    ctx = _ctx(tmp_path, restart_from=str(store))

    model = step_build_model(ctx)

    assert isinstance(model.initial, PriorState)
    assert model.initial.path == str(store)
    assert model.initial.sim_id is None
    np.testing.assert_array_equal(model.initial.head, np.arange(6, dtype=float).reshape(1, 6))


def test_a_hotstart_path_is_read_without_its_padding(tmp_path: Path) -> None:
    store = tmp_path / "prior.zarr"
    _write_prior(store, mesh=_mesh())
    ctx = _ctx(tmp_path, restart_from=f"  {store} ")

    model = step_build_model(ctx)

    assert isinstance(model.initial, PriorState)
    assert model.initial.path == str(store)


def test_a_hotstart_named_by_its_run_is_resolved(tmp_path: Path) -> None:
    sim_id = sealed_run(tmp_path, "first")
    _write_prior(tmp_path / "runs" / "first" / FIELDS_STORE_NAME, mesh=_mesh())
    ctx = _ctx(tmp_path, restart_from="first")

    model = step_build_model(ctx)

    assert model.initial.sim_id == sim_id
    assert model.initial.path == str(tmp_path / "runs" / "first" / FIELDS_STORE_NAME)


def test_a_hotstart_that_names_no_run_is_refused(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, restart_from="nowhere")

    with pytest.raises(ConfigError, match="names no field store"):
        step_build_model(ctx)


def test_a_hotstart_from_another_mesh_is_refused_before_the_solve(tmp_path: Path) -> None:
    store = tmp_path / "prior.zarr"
    _write_prior(store, mesh=_mesh(), moved=0.5)
    ctx = _ctx(tmp_path, restart_from=str(store))

    with pytest.raises(IncompatibleMeshError, match="another mesh"):
        step_build_model(ctx)
    assert ctx.setup.model is None


def test_a_hotstart_needs_the_cell_mesh(tmp_path: Path) -> None:
    store = tmp_path / "prior.zarr"
    _write_prior(store)
    ctx = _ctx(tmp_path, restart_from=str(store), mesh=False)

    with pytest.raises(ConfigError, match="cell mesh"):
        step_build_model(ctx)


# --- the three ways PrepareSolverStep reaches the step ---
# The persisted branch builds the model after the run is open and writes the
# profiles from it. A trial that writes nothing builds it too. A resume builds
# it again, so that a run resumed at run_solver finds one.


class _Store:
    def __init__(self, calls: list) -> None:
        self.calls = calls
        self.facts = SimpleNamespace()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _quiet(monkeypatch, calls: list, ctx) -> None:
    """Replace what the step writes on disk by records of the order of the calls."""
    store = _Store(calls)
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


def _persisted(ctx) -> None:
    ctx.execution.lightweight = False
    ctx.cfg.simulation = SimpleNamespace(
        results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=True))
    )


def test_the_persisted_branch_builds_the_model_after_the_run_opens(tmp_path, monkeypatch) -> None:
    ctx = _ctx(tmp_path)
    _persisted(ctx)
    ctx.setup.model = "built for an earlier run"
    calls: list = []
    _quiet(monkeypatch, calls, ctx)
    state = PipelineState(run_id="run", data={"ctx": ctx})

    PrepareSolverStep().run(state)

    assert isinstance(ctx.setup.model, Model)
    assert calls[0] == ("open", None)
    kind, profiles, domain = calls[1]
    assert kind == "params"
    assert profiles is ctx.setup.model.properties.profiles
    assert domain is None


def test_a_trial_that_writes_nothing_builds_the_model(tmp_path, monkeypatch) -> None:
    ctx = _ctx(tmp_path)
    calls: list = []
    _quiet(monkeypatch, calls, ctx)

    PrepareSolverStep().run(PipelineState(run_id="run", data={"ctx": ctx}))

    assert isinstance(ctx.setup.model, Model)
    assert calls == []


def test_a_trial_reads_a_hotstart_named_by_its_run(tmp_path, monkeypatch) -> None:
    sealed_run(tmp_path, "first")
    _write_prior(tmp_path / "runs" / "first" / FIELDS_STORE_NAME, mesh=_mesh())
    ctx = _ctx(tmp_path, restart_from="first")
    _quiet(monkeypatch, [], ctx)

    PrepareSolverStep().run(PipelineState(run_id="run", data={"ctx": ctx}))

    assert isinstance(ctx.setup.model.initial, PriorState)


@pytest.mark.parametrize("persisted", [False, True], ids=["not persisted", "persisted"])
def test_a_resume_builds_the_model_again(tmp_path, monkeypatch, persisted: bool) -> None:
    from tests._helpers.sealed_runs import write_attempt

    sealed_run(tmp_path, "first")
    _write_prior(tmp_path / "runs" / "first" / FIELDS_STORE_NAME, mesh=_mesh())
    ctx = _ctx(tmp_path, restart_from="first")
    calls: list = []
    _quiet(monkeypatch, calls, ctx)
    data = {"ctx": ctx}
    if persisted:
        _persisted(ctx)
        data["run_dir"] = write_attempt(tmp_path, "runs/run", status="failed", sim_id="sim-1")
    prior = PipelineState(run_id="run", step_index=5, data=data)

    PrepareSolverStep().rebuild_state(prior_state=prior, workspace=tmp_path, run_id="run")

    assert isinstance(ctx.setup.model, Model)
    assert isinstance(ctx.setup.model.initial, PriorState)
