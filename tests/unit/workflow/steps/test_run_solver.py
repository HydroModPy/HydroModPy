"""The run-solver step executes the plan through its launcher, with or without a run store."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import hydromodpy.workflow.steps.prepare_solver.dispatch as prepare_dispatch
import hydromodpy.workflow.steps.prepare_solver.facts as facts_mod
import hydromodpy.workflow.steps.run_solver as step_mod
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.solver.base import plan as plan_mod
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps import run_outputs
from hydromodpy.workflow.steps.run_solver import RunSolverStep


class _Launcher:
    """Stands for ``SimulationRunner``: records the call, returns canned results."""

    def __init__(self, executed: Any = ()) -> None:
        self.executed = executed
        self.calls: list[dict[str, Any]] = []

    def execute(self, plan: Any, ctx: Any, *, callbacks: Any, store: Any = None) -> Any:
        self.calls.append({"plan": plan, "ctx": ctx, "callbacks": callbacks, "store": store})
        return self.executed


def _ctx(*, persisted: bool, plan: Any = "PLAN", run_dir: Any = "/run") -> SimpleNamespace:
    return SimpleNamespace(
        sim_id="sim-1",
        run_dir=run_dir,
        execution=SimpleNamespace(
            simulation_plan=plan, lightweight=False, output_dirs_by_run_id={}
        ),
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


def test_run_without_a_store_executes_the_plan_and_advances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx(persisted=False)
    launcher = _Launcher()
    after = object()
    out = RunSolverStep(launcher=launcher).run(_state(ctx=ctx, after_process=after))
    assert launcher.calls[0]["store"] is None
    assert launcher.calls[0]["plan"] == "PLAN"
    assert launcher.calls[0]["callbacks"].after_process is after
    assert out.step_name == "run_solver"
    assert out.step_index == 4
    assert out.get("ctx") is ctx
    assert out.get("wall_seconds") >= 0


def test_run_with_a_store_records_metrics_dirs_and_what_the_model_says(
    monkeypatch: pytest.MonkeyPatch, store: _Store
) -> None:
    run_a = SimpleNamespace(id=7)
    run_b = SimpleNamespace(id=8)
    res_a = SimpleNamespace(solver_output_dir=Path("/out/a"))
    res_b = SimpleNamespace(solver_output_dir=None)
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
    ctx = _ctx(persisted=True)
    RunSolverStep(launcher=launcher).run(_state(ctx=ctx))
    assert launcher.calls[0]["store"] is store
    assert metrics == [(run_a, "sim-1", res_a), (run_b, "sim-1", res_b)]
    assert says == [(run_a, "sim-1"), (run_b, "sim-1")]
    assert store.facts.solver_output_dirs == {"7": "/out/a"}
    assert refreshed == [store]


def test_run_with_a_store_tolerates_a_launcher_returning_nothing(
    monkeypatch: pytest.MonkeyPatch, store: _Store
) -> None:
    monkeypatch.setattr(prepare_dispatch, "refresh_run_environment", lambda ctx, *, store: None)
    launcher = _Launcher(None)
    out = RunSolverStep(launcher=launcher).run(_state(ctx=_ctx(persisted=True)))
    assert out.step_name == "run_solver"
    assert store.facts.solver_output_dirs == {}


def test_run_builds_the_default_runner_without_a_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hydromodpy.solver.base.runner as runner_mod

    built = _Launcher()
    monkeypatch.setattr(runner_mod, "SimulationRunner", lambda: built)
    RunSolverStep().run(_state(ctx=_ctx(persisted=False)))
    assert len(built.calls) == 1


def test_run_without_ctx_raises() -> None:
    with pytest.raises(ConfigError, match="requires 'ctx'"):
        RunSolverStep(launcher=_Launcher()).run(_state())


def test_run_without_a_simulation_plan_raises() -> None:
    with pytest.raises(ConfigError, match="simulation_plan"):
        RunSolverStep(launcher=_Launcher()).run(_state(ctx=_ctx(persisted=False, plan=None)))


def test_the_step_declares_its_place_in_the_pipeline() -> None:
    assert RunSolverStep().depends_on() == ("prepare_solver",)
    assert RunSolverStep(launcher=_Launcher()).launcher is not None


def test_artifacts_is_empty_without_ctx_or_persistence_or_ids() -> None:
    step = RunSolverStep()
    assert step.artifacts(_state()) == ()
    assert step.artifacts(_state(ctx=_ctx(persisted=False))) == ()
    no_id = _ctx(persisted=True)
    no_id.sim_id = None
    assert step.artifacts(_state(ctx=no_id)) == ()
    assert step.artifacts(_state(ctx=_ctx(persisted=True, run_dir=None))) == ()


def test_artifacts_reads_the_paths_the_store_produced(
    monkeypatch: pytest.MonkeyPatch, store: _Store
) -> None:
    ctx = _ctx(persisted=True)
    monkeypatch.setattr(
        facts_mod,
        "store_sim_artifacts",
        lambda c, sim_id, *, store: (f"runs/{sim_id}/fields.zarr",) if c is ctx else (),
    )
    assert RunSolverStep().artifacts(_state(ctx=ctx)) == ("runs/sim-1/fields.zarr",)


def test_rebuild_state_without_ctx_raises() -> None:
    with pytest.raises(ConfigError, match="rebuild_state requires 'ctx'"):
        RunSolverStep().rebuild_state(prior_state=_state(), workspace=Path("."), run_id="r")


def test_rebuild_state_reads_runtime_and_output_dirs_from_the_facts(
    monkeypatch: pytest.MonkeyPatch, store: _Store
) -> None:
    store.facts.metrics = [
        SimpleNamespace(variable="head", metric="rmse", value=9.0),
        SimpleNamespace(variable="runtime", metric="duration_s", value=12.5),
    ]
    store.facts.solver_output_dirs = {"a": "/out/a", "b": "/out/b"}
    ctx = _ctx(persisted=True)
    out = RunSolverStep().rebuild_state(
        prior_state=_state(ctx=ctx), workspace=Path("."), run_id="r"
    )
    assert out.get("wall_seconds") == 12.5
    assert ctx.execution.output_dirs_by_run_id == {"a": Path("/out/a"), "b": Path("/out/b")}
    assert out.step_name == "run_solver"
    assert out.step_index == 4


def test_rebuild_state_of_a_run_without_store_has_no_wall_time() -> None:
    ctx = _ctx(persisted=False)
    out = RunSolverStep().rebuild_state(
        prior_state=_state(ctx=ctx), workspace=Path("."), run_id="r"
    )
    assert out.get("wall_seconds") is None
    assert ctx.execution.output_dirs_by_run_id == {}
