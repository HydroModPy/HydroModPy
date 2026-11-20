"""Running the steps of a cohort through an executor, in threads by default.

Each cohort is a tuple of items that may run side by side. Cohorts run one after the other.
"""

from __future__ import annotations

from contextvars import ContextVar

import pytest

import hydromodpy.workflow.parallel as parallel_module
from hydromodpy.core.exceptions import ConfigError


def test_cohorts_go_to_the_executor() -> None:
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


def test_zero_workers_is_refused() -> None:
    with pytest.raises(ConfigError, match="max_workers"):
        parallel_module.ThreadPoolCohortExecutor(max_workers=0)


def test_one_item_needs_no_pool(monkeypatch) -> None:
    def fail_pool(*_args, **_kwargs):
        raise AssertionError("ThreadPoolExecutor should not be used for one item")

    monkeypatch.setattr(parallel_module, "ThreadPoolExecutor", fail_pool)

    assert parallel_module.ThreadPoolCohortExecutor(max_workers=4).map(
        lambda item: item + 1, [2]
    ) == [3]


def test_items_run_in_a_copy_of_the_context() -> None:
    marker: ContextVar[str] = ContextVar("marker", default="unset")
    marker.set("caller")

    def read_and_overwrite(item: int) -> tuple[int, str]:
        seen = marker.get()
        marker.set(f"item {item}")
        return item, seen

    results = parallel_module.ThreadPoolCohortExecutor(max_workers=3).map(
        read_and_overwrite, [1, 2, 3]
    )

    assert results == [(1, "caller"), (2, "caller"), (3, "caller")]
    assert marker.get() == "caller"


def test_first_failure_in_item_order_is_raised() -> None:
    def fail_on_two(item: int) -> int:
        if item == 2:
            raise ValueError("item two failed")
        return item

    executor = parallel_module.ThreadPoolCohortExecutor(max_workers=2)

    with pytest.raises(ValueError, match="item two failed"):
        executor.map(fail_on_two, [1, 2, 3])
