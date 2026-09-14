"""Sweep orchestration and worker-pool helpers.

Hosts three reusable building blocks:

- :func:`expand_parameters` / :func:`run_sweep`: the original sweep API
  consumed by ``project.sweep``.
- :class:`SequentialExecutor` and :class:`ThreadPoolCohortExecutor`:
  cohort executors used by :class:`hydromodpy.workflow.runner.Pipeline`
  when a Kahn DAG sort returns multi-step cohorts.
- :func:`execute_cohorts`: thin helper that walks a list of cohorts and
  dispatches each to the executor of choice.

Threads are used over processes because every workflow step mutates a
live ``WorkflowContext`` whose components (zarr stores, DuckDB
connections) are not pickle-safe.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from hydromodpy.core import progress
from hydromodpy.core.exceptions import ConfigError


class SweepRun(Protocol):
    """Minimal run view needed by sweep orchestration."""

    sim_id: str


class SweepProject(Protocol):
    """Minimal project protocol needed by sweep orchestration."""

    def run(self, *, name: str | None = None, **overrides: float) -> SweepRun:
        """Execute one simulation and return its run view."""


def expand_parameters(
    parameters: dict[str, list[float] | dict],
    strategy: str,
) -> list[dict[str, float]]:
    """Return the list of {param: value} dicts that feed one run each."""
    if strategy == "enumerate":
        if len(parameters) != 1:
            raise ConfigError("strategy='enumerate' expects exactly one parameter")
        ((name, values),) = parameters.items()
        if isinstance(values, dict):
            raise ConfigError("strategy='enumerate' expects a list of values, not a spec")
        return [{name: float(v)} for v in values]

    if strategy == "grid":
        axes = []
        for name, values in parameters.items():
            if isinstance(values, dict):
                raise ConfigError("strategy='grid' expects lists of values, not specs")
            axes.append([(name, float(v)) for v in values])
        return [dict(combo) for combo in itertools.product(*axes)]

    raise NotImplementedError(f"strategy '{strategy}' is not supported yet")


def run_sweep(
    project: SweepProject,
    *,
    parameters: dict[str, list[float] | dict],
    strategy: str,
    name_template: str,
    parallel: int = 1,
) -> list[str]:
    """Execute one run per parameter point. Returns the sim_ids.

    ``parallel`` controls how many trials may run concurrently:

    - ``parallel <= 1`` keeps the legacy sequential loop.
    - ``parallel > 1`` dispatches trials through a thread pool. Threads
      are used over processes because the live ``Project`` (DuckDB
      catalog, Zarr store, in-memory ``WorkflowContext``) is not
      pickle-safe and a single project drives every trial.
    """
    if parallel < 1:
        raise ConfigError("run_sweep: 'parallel' must be >= 1")

    points = expand_parameters(parameters, strategy)
    if not points:
        return []

    with progress.task("Running parameter sweep", total=len(points)) as bar:

        def _one(point: dict[str, float]) -> str:
            param, value = next(iter(point.items()))
            name = name_template.format(param=param, value=value)
            with progress.suppressed():
                run = project.simulate(name=name, **point)
            bar.advance()
            return run.sim_id

        if parallel > 1 and len(points) > 1:
            raise ConfigError(
                "run_sweep parallel>1 is disabled: the sweep drives a single Project "
                "(one WorkflowContext, catalog and Zarr store) mutated per point with "
                "no lock, so concurrent points race on shared state. Run sequentially "
                "(parallel=1), or use 'hmp calibrate --parallel N', which forks an "
                "isolated per-trial context."
            )
        return [_one(point) for point in points]


# ---------------------------------------------------------------------------
# Cohort executors used by the Pipeline runner
# ---------------------------------------------------------------------------


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
    "SweepProject",
    "SweepRun",
    "ThreadPoolCohortExecutor",
    "execute_cohorts",
    "expand_parameters",
    "run_sweep",
)
