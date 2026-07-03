from __future__ import annotations

from types import SimpleNamespace

import pytest

import hydromodpy.workflow.parallel as parallel_module
from hydromodpy.core.exceptions import ConfigError


def test_expand_parameters_grid_preserves_axis_order() -> None:
    assert parallel_module.expand_parameters(
        {"hydraulic_conductivity": [1, 2], "storage": [0.1, 0.2]},
        "grid",
    ) == [
        {"hydraulic_conductivity": 1.0, "storage": 0.1},
        {"hydraulic_conductivity": 1.0, "storage": 0.2},
        {"hydraulic_conductivity": 2.0, "storage": 0.1},
        {"hydraulic_conductivity": 2.0, "storage": 0.2},
    ]


def test_expand_parameters_rejects_mismatched_strategy_specs() -> None:
    with pytest.raises(ConfigError, match="exactly one parameter"):
        parallel_module.expand_parameters({"k": [1.0], "sy": [0.2]}, "enumerate")

    with pytest.raises(ConfigError, match="expects lists of values"):
        parallel_module.expand_parameters({"k": {"min": 1.0, "max": 2.0}}, "grid")


def test_run_sweep_parallel_path_is_rejected_until_a_per_point_fork_exists() -> None:
    # parallel>1 shares one Project (context/catalog/store) mutated per point with
    # no lock, so it races: the sweep now refuses it instead of racing silently.
    class FakeProject:
        def simulate(self, *, name=None, **overrides):  # pragma: no cover - must not run
            raise AssertionError("run_sweep must not dispatch a racing parallel sweep")

    with pytest.raises(ConfigError, match="parallel>1 is disabled"):
        parallel_module.run_sweep(
            FakeProject(),
            parameters={"k": [1.0, 2.0]},
            strategy="enumerate",
            name_template="{param}_{value:g}",
            parallel=10,
        )


def test_run_sweep_rejects_invalid_parallel_before_expanding_parameters() -> None:
    class Project:
        def simulate(self, *, name: str | None = None, **overrides: float):
            raise AssertionError("simulate should not be called")

    with pytest.raises(ConfigError, match="parallel"):
        parallel_module.run_sweep(
            Project(),
            parameters={"k": {"min": 1.0, "max": 2.0}},
            strategy="grid",
            name_template="{param}_{value}",
            parallel=0,
        )


def test_run_sweep_sequential_default_path() -> None:
    """Without a ``parallel`` kwarg, run_sweep keeps sequential ordering."""

    class FakeProject:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def simulate(self, *, name: str | None = None, **overrides: float):
            sim_id = f"sim_{len(self.calls):02d}"
            self.calls.append({"name": name, **overrides})
            return SimpleNamespace(sim_id=sim_id)

    project = FakeProject()
    sim_ids = parallel_module.run_sweep(
        project,
        parameters={"K": [1.0, 2.0]},
        strategy="enumerate",
        name_template="K_{value:.2f}",
    )
    assert sim_ids == ["sim_00", "sim_01"]


def test_execute_cohorts_dispatches_each_cohort_to_the_selected_executor() -> None:
    class RecordingExecutor:
        def __init__(self) -> None:
            self.cohorts: list[tuple[str, ...]] = []

        def map(self, fn, items):
            self.cohorts.append(tuple(items))
            return [fn(item) for item in items]

    executor = RecordingExecutor()

    results = parallel_module.execute_cohorts(
        (("resolve", "load_data"), ("build_mesh",)),
        lambda item: item.upper(),
        executor=executor,
    )

    assert executor.cohorts == [("resolve", "load_data"), ("build_mesh",)]
    assert results == ["RESOLVE", "LOAD_DATA", "BUILD_MESH"]


def test_threadpool_cohort_executor_rejects_invalid_worker_count() -> None:
    with pytest.raises(ConfigError, match="max_workers"):
        parallel_module.ThreadPoolCohortExecutor(max_workers=0)


def test_threadpool_cohort_executor_runs_single_item_without_creating_pool(monkeypatch) -> None:
    def fail_pool(*_args, **_kwargs):
        raise AssertionError("ThreadPoolExecutor should not be used for one item")

    monkeypatch.setattr(parallel_module, "ThreadPoolExecutor", fail_pool)

    assert parallel_module.ThreadPoolCohortExecutor(max_workers=4).map(
        lambda item: item + 1, [2]
    ) == [3]
