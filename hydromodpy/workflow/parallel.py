"""Cohort executors of the workflow pipeline.

- :class:`SequentialExecutor` and :class:`ThreadPoolCohortExecutor`:
  cohort executors used by :class:`hydromodpy.workflow.runner.Pipeline`
  when a Kahn DAG sort returns multi-step cohorts.
- :func:`execute_cohorts`: thin helper that walks a list of cohorts and
  dispatches each to the executor of choice.

A sweep of parameter values is a set of recipes of a ``[sites]`` project, or
``hmp run --set``: it is not run from here.

Threads are used over processes because every workflow step mutates a
live ``WorkflowContext`` whose components (zarr stores, DuckDB
connections) are not pickle-safe.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from hydromodpy.core.exceptions import ConfigError


class CohortExecutor(Protocol):
    """Backend that runs every item of one Kahn cohort."""

    def map(
        self,
        fn: Callable[[Any], Any],
        items: Sequence[Any],
    ) -> list[Any]: ...


class SequentialExecutor:
    """In-process sequential executor for cohort items."""

    def map(self, fn: Callable[[Any], Any], items: Sequence[Any]) -> list[Any]:
        return [fn(item) for item in items]


class ThreadPoolCohortExecutor:
    """Cohort executor backed by a :class:`ThreadPoolExecutor`.

    Threads keep the GIL but are appropriate here: every workflow step
    mutates a shared :class:`WorkflowContext` whose live members
    (DuckDB connections, Zarr handles) are not pickle-safe. Threads
    also avoid spawning interpreters for the typical 2-3 step cohort.
    """

    def __init__(self, max_workers: int | None = None) -> None:
        if max_workers is not None and max_workers < 1:
            raise ConfigError("ThreadPoolCohortExecutor.max_workers must be >= 1")
        self._max_workers = max_workers

    def map(self, fn: Callable[[Any], Any], items: Sequence[Any]) -> list[Any]:
        if not items:
            return []
        if len(items) == 1:
            return [fn(items[0])]
        workers = self._max_workers if self._max_workers is not None else len(items)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(fn, items))


def execute_cohorts(
    cohorts: Iterable[Sequence[Any]],
    worker: Callable[[Any], Any],
    *,
    executor: CohortExecutor | None = None,
) -> list[Any]:
    """Walk Kahn cohorts and dispatch every item through ``executor``."""
    backend = executor if executor is not None else SequentialExecutor()
    results: list[Any] = []
    for cohort in cohorts:
        results.extend(backend.map(worker, list(cohort)))
    return results


__all__ = (
    "CohortExecutor",
    "SequentialExecutor",
    "ThreadPoolCohortExecutor",
    "execute_cohorts",
)
