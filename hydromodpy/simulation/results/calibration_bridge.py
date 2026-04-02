"""Calibration bridge: hot path (RAM) vs cold path (ResultStore).

During calibration, the optimizer runs hundreds of simulations. Each
iteration must be fast — no disk I/O in the inner loop. Only the best
result is persisted at the end.

The bridge provides:

- ``make_hot_simulator``: wraps a run function into a RAM-only callback
  that returns a 1D numpy vector of simulated values aligned with
  observations (the "calibration vector").
- ``persist_calibration_result``: after calibration converges, stores
  the best run into the ResultStore for archival and comparison.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def make_hot_simulator(
    run_fn: Callable[..., dict[str, pd.Series]],
    observation_plan: list[tuple[str, str, list]],
) -> Callable[..., np.ndarray]:
    """Wrap a solver run function into a RAM-only calibration callback.

    Parameters
    ----------
    run_fn : callable
        A function that runs one simulation and returns a dict mapping
        ``(station_id, variable)`` keys to pd.Series of simulated values.
        The function signature is ``run_fn(**params) -> dict``.
    observation_plan : list of (station_id, variable, timestamps)
        Defines which stations, variables, and time points to extract.
        This is the same format accepted by
        ``ResultStore.extract_calibration_vector``.

    Returns
    -------
    callable
        A function ``simulator(**params) -> np.ndarray`` that returns a
        1D vector of simulated values aligned with the observation plan.
        No disk I/O occurs — everything stays in RAM.
    """

    def simulator(**params) -> np.ndarray:
        results = run_fn(**params)
        parts = []
        for station_id, variable, timestamps in observation_plan:
            key = f"{station_id}_{variable}"
            ts = results.get(key)
            if ts is None:
                ts = results.get(station_id)
            if ts is None:
                ts = results.get(variable, pd.Series(dtype=float))

            ts_reindexed = ts.reindex(pd.DatetimeIndex(timestamps))
            parts.append(ts_reindexed.values)
        return np.concatenate(parts)

    return simulator


def persist_calibration_result(
    store: Any,
    sim_id: str,
    run_fn: Callable[..., dict[str, pd.Series]],
    best_params: dict,
    observation_plan: list[tuple[str, str, list]],
    *,
    solver: str = "unknown",
    name: str | None = None,
) -> None:
    """Re-run the best calibration result and persist it into the store.

    Parameters
    ----------
    store : ResultStore
        The result store to write into.
    sim_id : str
        Simulation UUID for the persisted result.
    run_fn : callable
        Same run function used during calibration.
    best_params : dict
        Best parameter set found by the optimizer.
    observation_plan : list of (station_id, variable, timestamps)
        Observation alignment plan.
    solver : str
        Solver name for registration.
    name : str, optional
        Human-readable name for the simulation.
    """
    store.register_simulation(sim_id, solver=solver, name=name or "calibration_best")

    results = run_fn(**best_params)

    for station_id, variable, timestamps in observation_plan:
        key = f"{station_id}_{variable}"
        ts = results.get(key)
        if ts is None:
            ts = results.get(station_id)
        if ts is None:
            ts = results.get(variable)
        if ts is not None:
            store.write_timeseries(sim_id, station_id, variable, ts)

    store.finalize(sim_id, status="calibrated")
    logger.info("Persisted calibration result for sim %s", sim_id)
