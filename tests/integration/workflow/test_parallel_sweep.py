"""Parallel sweep execution via :func:`run_sweep`.

Drives the public sweep entry point with ``parallel > 1`` against a fake
project so the test stays fully in-process and free of solver binaries.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from hydromodpy.workflow.parallel import run_sweep


class _FakeRun:
    """Minimal stand-in matching the :class:`SweepRun` protocol."""

    def __init__(self, sim_id: str) -> None:
        self.sim_id = sim_id


class _FakeProject:
    """Records every call and emits a unique sim_id per parameter point."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[dict[str, object]] = []

    def simulate(self, *, name: str | None = None, **overrides: float) -> _FakeRun:
        with self._lock:
            sim_id = f"sim_{len(self.calls):02d}"
            self.calls.append({"name": name, **overrides})
        return _FakeRun(sim_id)


def test_run_sweep_parallel_returns_four_sim_ids() -> None:
    """A 4-trial sweep with ``parallel=2`` collects 4 unique sim_ids."""
    project = _FakeProject()
    sim_ids = run_sweep(
        project,
        parameters={"K": [1.0, 2.0, 3.0, 4.0]},
        strategy="enumerate",
        name_template="K_{value:.2f}",
        parallel=2,
    )
    assert len(sim_ids) == 4
    assert len(set(sim_ids)) == 4
    assert {call["K"] for call in project.calls} == {1.0, 2.0, 3.0, 4.0}


def test_run_sweep_sequential_default_path() -> None:
    """``parallel=1`` keeps the legacy sequential semantics."""
    project = _FakeProject()
    sim_ids = run_sweep(
        project,
        parameters={"K": [1.0, 2.0]},
        strategy="enumerate",
        name_template="K_{value:.2f}",
    )
    assert sim_ids == ["sim_00", "sim_01"]


def test_run_sweep_parallel_rejects_zero() -> None:
    """``parallel < 1`` raises a :class:`ConfigError`."""
    from hydromodpy.core.exceptions import ConfigError

    project = _FakeProject()
    try:
        run_sweep(
            project,
            parameters={"K": [1.0]},
            strategy="enumerate",
            name_template="K_{value:.2f}",
            parallel=0,
        )
    except ConfigError:
        return
    raise AssertionError("run_sweep should reject parallel < 1")


def test_project_runner_sweep_passes_parallel_through(monkeypatch) -> None:
    """``ProjectRunner.sweep`` forwards ``parallel`` to ``run_sweep``."""
    from hydromodpy.project.runner import ProjectRunner

    captured: dict[str, object] = {}

    def fake_run_sweep(project, *, parameters, strategy, name_template, parallel):
        captured["parallel"] = parallel
        return ["sim_a", "sim_b"]

    monkeypatch.setattr("hydromodpy.workflow.parallel.run_sweep", fake_run_sweep)
    project = SimpleNamespace(_store=None, _ensure_model_built=lambda: None)

    ProjectRunner(project).sweep({"K": [1.0, 2.0]}, parallel=3)

    assert captured["parallel"] == 3


def test_pipeline_uses_threadpool_executor_by_default() -> None:
    """``Pipeline`` selects :class:`ThreadPoolCohortExecutor` when no flag is set.

    Construction-only assertion: we never call ``run`` because that would
    require a fully wired ``WorkflowContext``. The ``_parallel`` flag is
    the single switch toggled at ``run(parallel=...)`` time.
    """
    from hydromodpy.workflow.runner import Pipeline

    pipeline = Pipeline(steps=())
    assert pipeline._parallel is True
