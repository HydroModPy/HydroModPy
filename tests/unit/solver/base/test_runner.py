from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.solver.base.plan import ProcessRun, RunExecutionResult, SimulationPlan
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.base.runner import ProcessCallbacks, SimulationRunner


class _FailingAdapter:
    def execute(self, _ctx):
        raise RuntimeError("solver failed")


def test_after_process_runs_when_process_run_fails(monkeypatch) -> None:
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: _FailingAdapter())

    events: list[str] = []
    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id="custom_main::broken",
                process_id="custom_main",
                process_type="custom",
                solver="broken",
            ),
        ),
    )
    state = SimpleNamespace(
        cfg=None,
        setup=SimpleNamespace(),
        execution=SimpleNamespace(models_by_run_id={}),
        sim_id=None,
    )
    runner = SimulationRunner(
        callbacks=ProcessCallbacks(
            before_process=lambda name: events.append(f"before:{name}"),
            after_process=lambda name: events.append(f"after:{name}"),
        )
    )

    with pytest.raises(RuntimeError, match="solver failed"):
        runner.execute(plan, state)

    assert events == ["before:custom", "after:custom"]


class _RecordingAdapter:
    def __init__(self) -> None:
        self.contexts: list[object] = []

    def execute(self, ctx):
        self.contexts.append(ctx)
        return RunExecutionResult(primary_model=None)


def _flow_plan() -> SimulationPlan:
    return SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id="flow_main::modflow6",
                process_id="flow_main",
                process_type="flow",
                solver="modflow6",
            ),
        ),
    )


def _flow_state(**setup) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=None,
        setup=SimpleNamespace(**setup),
        execution=SimpleNamespace(models_by_run_id={}, output_dirs_by_run_id={}),
        sim_id=None,
    )


def test_a_flow_run_needs_the_model_that_prepare_solver_builds(monkeypatch) -> None:
    """The runner refuses a flow run without ``setup.model`` before the adapter is called."""
    adapter = _RecordingAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)

    for setup in ({}, {"model": None}):
        with pytest.raises(ConfigError, match="prepare_solver"):
            SimulationRunner().execute(_flow_plan(), _flow_state(**setup))

    assert adapter.contexts == []


def test_a_flow_run_with_its_model_reaches_the_adapter_and_creates_no_flow(monkeypatch) -> None:
    adapter = _RecordingAdapter()
    monkeypatch.setattr(solvers, "create", lambda *_parts, **_options: adapter)
    model = object()
    state = _flow_state(model=model, flow=None)

    SimulationRunner().execute(_flow_plan(), state)

    assert len(adapter.contexts) == 1
    assert adapter.contexts[0].state.setup.model is model
    assert state.setup.flow is None
