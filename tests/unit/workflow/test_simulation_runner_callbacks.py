from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.simulation.execution.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan


class _FailingAdapter:
    def execute(self, _ctx):
        raise RuntimeError("solver failed")


def test_after_process_runs_when_process_run_fails(monkeypatch) -> None:
    from hydromodpy.simulation import _solver_protocol

    class _FakeProvider:
        def get_solver_adapter(self, _process_type: str, _solver_name: str):
            return _FailingAdapter()

    monkeypatch.setattr(_solver_protocol, "_PROVIDER", _FakeProvider())

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
    state = SimpleNamespace(execution=SimpleNamespace(models_by_run_id={}))
    runner = SimulationRunner(
        callbacks=ProcessCallbacks(
            before_process=lambda name: events.append(f"before:{name}"),
            after_process=lambda name: events.append(f"after:{name}"),
        )
    )

    with pytest.raises(RuntimeError, match="solver failed"):
        runner.execute(plan, state)

    assert events == ["before:custom", "after:custom"]
