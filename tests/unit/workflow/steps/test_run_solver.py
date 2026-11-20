"""The run-solver step executes the plan through its launcher, with or without a run store.

With a store it records the metrics, the solver output folders and the solve lines of
the profile (durations in s). On a resume it rebuilds the solver runs from the facts."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

import hydromodpy.workflow.steps.prepare_solver.dispatch as prepare_dispatch
import hydromodpy.workflow.steps.prepare_solver.facts as facts_mod
import hydromodpy.workflow.steps.run_solver as step_mod
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.storage.run_profile import read_profile
from hydromodpy.solver.base import plan as plan_mod
from hydromodpy.solver.base.plan import ProcessRun, SimulationPlan
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps import run_outputs
from hydromodpy.workflow.steps.run_solver import RunSolverStep
from tests._helpers.fake_solvers import fake_adapter


class _Launcher:
    """Stands for ``SimulationRunner``: records the call, returns canned results."""

    def __init__(self, executed: Any = ()) -> None:
        self.executed = executed
        self.calls: list[dict[str, Any]] = []

    def execute(self, plan: Any, ctx: Any, *, callbacks: Any = None, store: Any = None) -> Any:
        self.calls.append({"plan": plan, "ctx": ctx, "callbacks": callbacks, "store": store})
        return self.executed


def _ctx(*, persisted: bool, plan: Any = "PLAN", run_dir: Any = "/run") -> SimpleNamespace:
    return SimpleNamespace(
        sim_id="sim-1",
        run_dir=run_dir,
        attempt=1,
        execution=SimpleNamespace(simulation_plan=plan, lightweight=False, solver_runs={}),
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(
                results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=persisted))
            )
        ),
    )


def _state(**data: Any) -> PipelineState:
    return PipelineState(run_id="r", step_index=3, data=data)


class _Store:
    def __init__(self, metrics: Any = (), dirs: Any = None) -> None:
        self.facts = SimpleNamespace(metrics=list(metrics), solver_output_dirs=dict(dirs or {}))


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    fake = _Store()

    @contextmanager
    def opened(ctx: Any):
        yield fake

    monkeypatch.setattr(step_mod, "run_store", opened)
    return fake


def test_run_records_metrics_dirs_and_model_says(
    monkeypatch: pytest.MonkeyPatch, store: _Store, tmp_path: Path
) -> None:
    run_a = SimpleNamespace(id=7)
    run_b = SimpleNamespace(id=8)
    res_a = SimpleNamespace(output_dir=Path("/out/a"), solve_s=1.5, reran=False)
    res_b = SimpleNamespace(output_dir=None, solve_s=None, reran=False)
    metrics: list[Any] = []
    says: list[Any] = []
    refreshed: list[Any] = []
    monkeypatch.setattr(
        plan_mod.RunContext, "of", lambda ctx, *, plan, run, store: SimpleNamespace(run=run)
    )
    monkeypatch.setattr(
        run_outputs,
        "record_run_execution_metrics",
        lambda *, ctx, sim_id, store, result: metrics.append((ctx.run, sim_id, result)),
    )
    monkeypatch.setattr(
        run_outputs,
        "record_what_the_model_says",
        lambda *, ctx, sim_id, store: says.append((ctx.run, sim_id)),
    )
    monkeypatch.setattr(
        prepare_dispatch, "refresh_run_environment", lambda ctx, *, store: refreshed.append(store)
    )
    launcher = _Launcher([(run_a, res_a), (run_b, res_b)])
    ctx = _ctx(persisted=True, run_dir=tmp_path)
    RunSolverStep(launcher=launcher).run(_state(ctx=ctx))
    assert launcher.calls[0]["store"] is None
    assert metrics == [(run_a, "sim-1", res_a), (run_b, "sim-1", res_b)]
    assert says == [(run_a, "sim-1"), (run_b, "sim-1")]
    assert store.facts.solver_output_dirs == {"7": "/out/a"}
    assert refreshed == [store]


def test_profile_solve_lines(
    monkeypatch: pytest.MonkeyPatch, store: _Store, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        plan_mod.RunContext, "of", lambda ctx, *, plan, run, store: SimpleNamespace(run=run)
    )
    monkeypatch.setattr(run_outputs, "record_run_execution_metrics", lambda **_: None)
    monkeypatch.setattr(run_outputs, "record_what_the_model_says", lambda **_: None)
    monkeypatch.setattr(prepare_dispatch, "refresh_run_environment", lambda ctx, *, store: None)
    executed = [
        (SimpleNamespace(id="flow"), SimpleNamespace(output_dir=None, solve_s=2.5, reran=True)),
        (SimpleNamespace(id="mesh"), SimpleNamespace(output_dir=None, solve_s=None, reran=False)),
        (
            SimpleNamespace(id="transport"),
            SimpleNamespace(output_dir=None, solve_s=0.5, reran=False),
        ),
    ]
    ctx = _ctx(persisted=True, run_dir=tmp_path)
    ctx.attempt = 2
    RunSolverStep(launcher=_Launcher(executed)).run(_state(ctx=ctx))

    lines = read_profile(tmp_path).lines
    assert [(line.kind, line.name, line.attempt, line.reused) for line in lines] == [
        ("solve", "flow", 2, "rerun"),
        ("solve", "transport", 2, "no"),
    ]
    assert [line.duration_s for line in lines] == [2.5, 0.5]
    assert lines[1].started_at - lines[0].started_at == timedelta(seconds=2.5)


def test_default_runner_without_a_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hydromodpy.solver.base.runner as runner_mod

    built = _Launcher()
    monkeypatch.setattr(runner_mod, "SimulationRunner", lambda: built)
    RunSolverStep().run(_state(ctx=_ctx(persisted=False)))
    assert len(built.calls) == 1


RUN_REFUSALS = [
    pytest.param({}, "requires 'ctx'", id="no context"),
    pytest.param({"ctx": _ctx(persisted=False, plan=None)}, "simulation_plan", id="no plan"),
]


@pytest.mark.parametrize(("data", "message"), RUN_REFUSALS)
def test_run_refusals(data, message) -> None:
    with pytest.raises(ConfigError, match=message):
        RunSolverStep(launcher=_Launcher()).run(_state(**data))


def test_no_artifacts_without_a_stored_run() -> None:
    step = RunSolverStep()
    assert step.artifacts(_state()) == ()
    assert step.artifacts(_state(ctx=_ctx(persisted=False))) == ()
    no_id = _ctx(persisted=True)
    no_id.sim_id = None
    assert step.artifacts(_state(ctx=no_id)) == ()
    assert step.artifacts(_state(ctx=_ctx(persisted=True, run_dir=None))) == ()


def test_artifacts_from_the_store(monkeypatch: pytest.MonkeyPatch, store: _Store) -> None:
    ctx = _ctx(persisted=True)
    monkeypatch.setattr(
        facts_mod,
        "store_sim_artifacts",
        lambda c, sim_id, *, store: (f"runs/{sim_id}/fields.zarr",) if c is ctx else (),
    )
    assert RunSolverStep().artifacts(_state(ctx=ctx)) == ("runs/sim-1/fields.zarr",)


def test_rebuild_needs_a_context() -> None:
    with pytest.raises(ConfigError, match="rebuild_state requires 'ctx'"):
        RunSolverStep().rebuild_state(prior_state=_state(), workspace=Path("."), run_id="r")


def _resumed_ctx(*runs: ProcessRun, solver_options: Any = None) -> SimpleNamespace:
    ctx = _ctx(persisted=True, plan=SimulationPlan(name="run", description="run", runs=runs))
    ctx.setup = SimpleNamespace(model="the model of the run")
    ctx.cfg.solver = SimpleNamespace(options_of=lambda name: solver_options)
    return ctx


MESH = ProcessRun(id="mesh::catchment", process_id="mesh", process_type="mesh", solver="catchment")
FLOW = ProcessRun(id="flow::fake", process_id="flow", process_type="flow", solver="fake")


def test_rebuild_reads_output_dirs_from_facts(
    monkeypatch: pytest.MonkeyPatch, store: _Store, isolated_solvers
) -> None:
    isolated_solvers.solvers.register(fake_adapter("fake"))
    store.facts.metrics = [SimpleNamespace(variable="head", metric="rmse", value=9.0)]
    store.facts.solver_output_dirs = {FLOW.id: "/scratch/island", MESH.id: "/scratch/mesh"}
    ctx = _resumed_ctx(MESH, FLOW)
    out = RunSolverStep().rebuild_state(
        prior_state=_state(ctx=ctx), workspace=Path("."), run_id="r"
    )
    assert "wall_seconds" not in out.data
    assert out.step_name == "run_solver"
    assert out.step_index == 4

    resumed = ctx.execution.solver_runs
    assert set(resumed) == {FLOW.id, MESH.id}
    run = resumed[FLOW.id]
    assert run.output_dir == Path("/scratch/island")
    assert (run.slot.folder, run.slot.name) == (Path("/scratch"), "island")
    assert (run.written, run.solved) == (True, True)
    assert run.solver_model is None, "no solver object is rebuilt on a resume"
    assert run.model == "the model of the run"


def test_resumed_flow_run_gets_its_options(store: _Store, isolated_solvers) -> None:
    class _Table(BaseModel):
        pass

    table = _Table()
    isolated_solvers.solvers.register(fake_adapter("fake", options=_Table))
    store.facts.solver_output_dirs = {FLOW.id: "/scratch/island", MESH.id: "/scratch/mesh"}
    ctx = _resumed_ctx(MESH, FLOW, solver_options=table)

    RunSolverStep().rebuild_state(prior_state=_state(ctx=ctx), workspace=Path("."), run_id="r")

    assert ctx.execution.solver_runs[FLOW.id].options is table
    assert ctx.execution.solver_runs[MESH.id].options is None, "a mesh run has no backend"
