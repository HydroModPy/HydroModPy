"""The environment of a launched case, and the thread budget its worker applies.

Why
---
A child of the launcher is an ordinary ``hmp run <case>.toml``. What makes
it a launched case is its environment, built here:

- ``HMP_RUN_SCRATCH`` is removed. It names the scratch folder of the run the
  current process is inside; a child that inherited it would work in the
  folder of its parent instead of claiming its own.
- ``HMP_SET_*`` are removed. The plan rendered them into each case, and a
  worker of the plan refuses them.
- ``HMP_LAUNCHED_CASE`` says who launched the case. The worker then leaves
  the index to the launcher, which refreshes it after every case.
- ``HMP_THREADS_PER_CASE`` carries ``[sites.run] threads_per_case``. The
  worker applies it at its entry (:func:`apply_thread_budget`): the native
  thread pools of the process through ``threadpoolctl``, and the usual
  variables for the processes it starts itself.
- ``HMP_DATA_CACHE_PRIVATE`` names the private data cache of the child. The
  child then opens the shared workspace cache read-only, one request at a
  time, and writes what it registers into its private cache, which the
  launcher merges once the child has ended.

The same variables are what a scheduler script sets for each task.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from hydromodpy.core.state.paths import RUN_SCRATCH_ENV
from hydromodpy.core.toml_io.overrides import ENV_SET_PREFIX
from hydromodpy.data.registry.catalog_duckdb import PRIVATE_CACHE_ENV

LAUNCHED_ENV = "HMP_LAUNCHED_CASE"
"""Who launched the case (``local``, ``slurm``); the launcher indexes, not the case."""

THREADS_ENV = "HMP_THREADS_PER_CASE"
"""Threads one launched case may use, set by the launcher or the array script."""

THREAD_LIMIT_VARIABLES: tuple[str, ...] = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
"""Variables the native libraries of the child processes read for their pool size."""


def child_environment(
    base: Mapping[str, str],
    *,
    threads_per_case: int,
    private_cache: Path | None,
) -> dict[str, str]:
    """Return the environment of one launched case, built from *base*."""
    env = {
        key: value
        for key, value in base.items()
        if key != RUN_SCRATCH_ENV and not key.startswith(ENV_SET_PREFIX)
    }
    env[THREADS_ENV] = str(int(threads_per_case))
    if private_cache is None:
        env.pop(PRIVATE_CACHE_ENV, None)
    else:
        env[PRIVATE_CACHE_ENV] = str(private_cache)
    return env


def threads_of(env: Mapping[str, str]) -> int | None:
    """Return the thread budget *env* carries, or ``None`` when it carries none.

    Raises :class:`ValueError` on a value that is not a positive integer.
    """
    text = env.get(THREADS_ENV, "").strip()
    if not text:
        return None
    value = int(text)
    if value < 1:
        raise ValueError(f"{THREADS_ENV}={text!r}: a thread budget is a positive integer")
    return value


def apply_thread_budget(env: Mapping[str, str] | None = None) -> int | None:
    """Bound the threads of this process to the budget of its case; return it.

    Does nothing and returns ``None`` outside a launched case. Inside one, the
    native pools already loaded are limited through ``threadpoolctl`` and the
    limit variables are written into ``os.environ`` for the processes this
    worker starts.
    """
    budget = threads_of(os.environ if env is None else env)
    if budget is None:
        return None
    for name in THREAD_LIMIT_VARIABLES:
        os.environ[name] = str(budget)
    from threadpoolctl import threadpool_limits

    threadpool_limits(limits=budget)
    return budget


__all__ = [
    "LAUNCHED_ENV",
    "THREADS_ENV",
    "THREAD_LIMIT_VARIABLES",
    "apply_thread_budget",
    "child_environment",
    "threads_of",
]
