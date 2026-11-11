"""The run-solver step executes the plan through its launcher, with or without a run store."""

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
from hydromodpy.results.storage.run_profile import collected_profile, read_profile
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
    assert "wall_seconds" not in out.data, "the time of the solve is in profile.json, not the state"


def test_run_with_a_store_records_metrics_dirs_and_what_the_model_says(
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


def test_the_solve_line_of_the_profile_comes_from_the_solve_time_of_each_run(
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


def test_a_run_without_a_directory_writes_no_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = SimpleNamespace(id="flow")
    result = SimpleNamespace(output_dir=None, solve_s=1.0, reran=False)
    RunSolverStep(launcher=_Launcher([(run, result)])).run(
        _state(ctx=_ctx(persisted=False, run_dir=None))
    )
    assert not list(tmp_path.iterdir())


LIGHT_SOLVES: tuple[tuple[str, bool, str], ...] = (
    ("a built run", False, "no"),
    ("a rerun", True, "rerun"),
)


@pytest.mark.parametrize(
    ("case", "reran", "reused"), LIGHT_SOLVES, ids=[c for c, *_ in LIGHT_SOLVES]
)
def test_a_trial_without_a_store_profiles_its_solves_into_its_collector(
    case: str, reran: bool, reused: str
) -> None:
    del case
    run = SimpleNamespace(id="flow")
    result = SimpleNamespace(output_dir=None, solve_s=0.75, reran=reran)
    with collected_profile() as lines:
        RunSolverStep(launcher=_Launcher([(run, result)])).run(
            _state(ctx=_ctx(persisted=False, run_dir=None))
        )
    assert [(line.kind, line.name, line.duration_s, line.reused) for line in lines] == [
        ("solve", "flow", 0.75, reused)
    ]


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


def _resumed_ctx(*runs: ProcessRun, solver_options: Any = None) -> SimpleNamespace:
    ctx = _ctx(persisted=True, plan=SimulationPlan(name="run", description="run", runs=runs))
    ctx.setup = SimpleNamespace(model="the model of the run")
    ctx.cfg.solver = SimpleNamespace(options_of=lambda name: solver_options)
    return ctx


MESH = ProcessRun(id="mesh::catchment", process_id="mesh", process_type="mesh", solver="catchment")
FLOW = ProcessRun(id="flow::fake", process_id="flow", process_type="flow", solver="fake")


def test_rebuild_state_reads_the_output_dirs_from_the_facts(
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


def test_a_resumed_flow_run_gets_the_options_the_runner_would_have_given_it(
    store: _Store, isolated_solvers
) -> None:
    class _Table(BaseModel):
        pass

    table = _Table()
    isolated_solvers.solvers.register(fake_adapter("fake", options=_Table))
    store.facts.solver_output_dirs = {FLOW.id: "/scratch/island", MESH.id: "/scratch/mesh"}
    ctx = _resumed_ctx(MESH, FLOW, solver_options=table)

    RunSolverStep().rebuild_state(prior_state=_state(ctx=ctx), workspace=Path("."), run_id="r")

    assert ctx.execution.solver_runs[FLOW.id].options is table
    assert ctx.execution.solver_runs[MESH.id].options is None, "a mesh run has no backend"


def test_a_folder_of_a_run_the_plan_no_longer_holds_is_put_back_without_options(
    store: _Store,
) -> None:
    store.facts.solver_output_dirs = {"flow::gone": "/scratch/gone"}
    ctx = _resumed_ctx(MESH)

    RunSolverStep().rebuild_state(prior_state=_state(ctx=ctx), workspace=Path("."), run_id="r")

    assert ctx.execution.solver_runs["flow::gone"].options is None
