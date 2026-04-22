"""Calibration bridge: hot path (RAM) vs cold path (SimulationCatalog).

During calibration, the optimizer runs hundreds of simulations. Each
iteration must be fast — no disk I/O in the inner loop. Only the best
result is persisted at the end.

The bridge provides:

- ``make_hot_simulator``: wraps a run function into a RAM-only callback
  that returns a 1D numpy vector of simulated values aligned with
  observations (the "calibration vector").
- ``persist_calibration_result``: after calibration converges, stores
  the best run into the SimulationCatalog for archival and comparison.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

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
        ``SimulationCatalog.extract_calibration_vector``.

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
    project: str = "calibration",
    solver: str = "unknown",
    name: str | None = None,
    metrics: list[tuple[str, str, float]] | None = None,
) -> None:
    store.register_simulation(
        sim_id,
        project=project,
        solver=solver,
        name=name or "calibration_best",
    )

    try:
        results = run_fn(**best_params)

        for station_id, variable, timestamps in observation_plan:
            key = f"{station_id}_{variable}"
            ts = results.get(key)
            if ts is None:
                ts = results.get(station_id)
            if ts is None:
                ts = results.get(variable)
            if ts is not None:
                store.write_timeseries(sim_id, station_id, variable, ts, unit="")

        if metrics:
            for station_id, metric_name, value in metrics:
                store.write_metric(sim_id, station_id, metric_name, value)

        store.write_parameters(
            sim_id,
            [
                {"param_name": k, "value": v, "parameterization": "calibrated"}
                for k, v in best_params.items()
            ],
        )
    except Exception:
        store.finalize(sim_id, status="failed")
        raise

    store.finalize(sim_id, status="completed")
    logger.info("Persisted calibration result for sim %s", sim_id)


def persist_calibration_summary_to_store(
    store: Any,
    sim_id: str,
    *,
    best_params: dict,
    best_objective: float,
    method: str,
    iteration_count: int,
    score_best: float | None = None,
    solver: str | None = None,
    calibration_id: str | None = None,
) -> None:
    """Persist a lightweight calibration summary into the SimulationCatalog.

    Unlike :func:`persist_calibration_result`, this does **not** re-run the
    simulation.  It only records the optimizer output (best parameters,
    objective value, method, iteration count) so that the calibration
    outcome is discoverable from the store.

    Parameters
    ----------
    store : SimulationCatalog
        The result store to write into.
    sim_id : str
        Simulation UUID for the persisted record.
    best_params : dict
        Best parameter set found by the optimizer.
    best_objective : float
        Best objective (cost) value.
    method : str
        Optimization method used (e.g. ``"nelder_mead"``, ``"differential_evolution"``).
    iteration_count : int
        Total number of objective evaluations.
    score_best : float, optional
        Best score value (higher-is-better metric), if available.
    solver : str, optional
        Solver name for registration metadata.
    calibration_id : str, optional
        Human-readable calibration session identifier.
    """
    name = calibration_id or "calibration_best"
    store.register_simulation(
        sim_id,
        project="calibration",
        solver=solver or "calibration",
        name=name,
        tags=["calibration"],
    )

    # Persist summary metrics under a synthetic "__calibration__" station so
    # they are queryable through the standard metrics table.
    station = "__calibration__"
    store.write_metric(sim_id, station, "objective_best", best_objective)
    store.write_metric(sim_id, station, "iteration_count", float(iteration_count))
    if score_best is not None:
        store.write_metric(sim_id, station, "score_best", score_best)

    # Write calibration params enriched with metadata so the method and
    # objective are recoverable from the single JSON blob.
    params_with_meta = dict(best_params)
    params_with_meta["__method__"] = method
    params_with_meta["__iteration_count__"] = iteration_count
    params_with_meta["__objective_best__"] = best_objective
    if score_best is not None:
        params_with_meta["__score_best__"] = score_best
    store.write_parameters(
        sim_id,
        [
            {"param_name": k, "value": v, "parameterization": "calibrated"}
            for k, v in params_with_meta.items()
        ],
    )

    store.finalize(sim_id, status="completed")
    logger.info(
        "Persisted calibration summary for sim %s (method=%s, objective=%.6g, iterations=%d)",
        sim_id,
        method,
        best_objective,
        iteration_count,
    )
