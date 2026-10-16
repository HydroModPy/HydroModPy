from __future__ import annotations

import pytest

import hydromodpy.workflow.parallel as parallel_module
from hydromodpy.core.exceptions import ConfigError


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
