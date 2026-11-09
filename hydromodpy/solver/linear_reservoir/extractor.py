"""The extractor the linear reservoir registers under its adapter key.

It reads the two files the solve wrote in the slot of the run and writes the
results of the run: the mean discharge and the storage depth at the station
of the whole catchment, and the three terms of the budget at the domain
zone, one row per period, closed on the mass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.scope import CATCHMENT, DOMAIN
from hydromodpy.core.time.window import time_grid_start
from hydromodpy.core.units.time import CF_EPOCH, CF_TIME_UNITS, cf_time_axis_seconds
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.plan import SolverRun
from hydromodpy.solver.linear_reservoir.adapter import SERIES_FILE


class LinearReservoirExtractor:
    """Write the series and the budget rows of one solved run into a run store."""

    process_type: str = "flow"
    solver_name: str = "linear_reservoir"

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Read the series of the run and write its results into ``store``.

        ``retention`` says which per-cell budget terms a run keeps. The
        reservoir holds one cell and writes no per-cell field, so a full
        policy and a consumers policy read the same table back.
        """
        sim_id = store.sim_id
        solver_output_dir = Path(solver_run.output_dir)
        series_path = solver_output_dir / SERIES_FILE
        if not series_path.is_file():
            from hydromodpy.core.exceptions import NothingThereError

            raise NothingThereError(f"No {SERIES_FILE} in {solver_output_dir}")
        frame = pd.read_csv(series_path, index_col="time", parse_dates=True)
        if frame.index.size == 0:
            from hydromodpy.core.exceptions import NothingThereError

            raise NothingThereError(f"{series_path} holds no period of the run.")
        self._write_time_axis(sim_id, store, solver_run, frame)
        store.write_timeseries(
            sim_id, CATCHMENT, "discharge", frame["discharge_m3_s"], unit="m3 s-1"
        )
        store.write_timeseries(
            sim_id, CATCHMENT, "reservoir_storage", frame["reservoir_storage_m"], unit="m"
        )
        self._write_budget_rows(sim_id, store, solver_run, frame)

    def _write_time_axis(
        self, sim_id: str, store: Any, solver_run: SolverRun, frame: pd.DataFrame
    ) -> None:
        """Stamp every period of the run at its end, like the other extractors."""
        start = time_grid_start(None if solver_run.model is None else solver_run.model.time.grid)
        elapsed = frame.index.to_numpy(dtype="datetime64[s]") - np.datetime64(start)
        seconds = elapsed.astype(float)
        writer = getattr(store, "write_time", None)
        if writer is None:
            raise TypeError("Simulation store must implement write_time().")
        writer(sim_id, cf_time_axis_seconds(seconds, start), epoch=CF_EPOCH, units=CF_TIME_UNITS)

    def _write_budget_rows(
        self, sim_id: str, store: Any, solver_run: SolverRun, frame: pd.DataFrame
    ) -> None:
        """Write one row per term and per period, in the sign every solver uses.

        The recharge enters the cell, the drain to the outlet leaves it, and
        the storage term reads ``-A ds/dt`` in the sign of ``core/budget``:
        positive when the state falls, so the three terms of one period sum
        to zero, the leftover of the mass by construction of the kernel.
        """
        area_m2 = float(solver_run.solver_model.area_m2)
        initial_depth_m = float(solver_run.solver_model.initial_depth_m)
        grid = solver_run.model.time.grid
        lengths = getattr(grid, "period_lengths_seconds", None)
        if lengths is None or len(lengths) != frame.index.size:
            from hydromodpy.core.exceptions import NothingThereError

            raise NothingThereError(
                "the run carries "
                f"{0 if lengths is None else len(lengths)} periods of the time grid "
                f"and {frame.index.size} rows of series: one row per period."
            )
        recharges = frame["recharge_m_s"].to_numpy(dtype=float)
        discharges = frame["discharge_m3_s"].to_numpy(dtype=float)
        stored = frame["reservoir_storage_m"].to_numpy(dtype=float)
        records: list[dict[str, float | str | int]] = []
        previous = initial_depth_m
        for index in range(frame.index.size):
            recharge_rate = recharges[index] * area_m2
            discharge_rate = discharges[index]
            storage_rate = (stored[index] - previous) * area_m2 / float(lengths[index])
            previous = stored[index]
            records.append(
                {
                    "timestep": index,
                    "zone_id": DOMAIN,
                    "component": "recharge",
                    "flux_in": recharge_rate,
                    "flux_out": 0.0,
                    "unit": "m3 s-1",
                }
            )
            records.append(
                {
                    "timestep": index,
                    "zone_id": DOMAIN,
                    "component": "drain",
                    "flux_in": 0.0,
                    "flux_out": discharge_rate,
                    "unit": "m3 s-1",
                }
            )
            records.append(
                {
                    "timestep": index,
                    "zone_id": DOMAIN,
                    "component": "storage",
                    "flux_in": max(-storage_rate, 0.0),
                    "flux_out": max(storage_rate, 0.0),
                    "unit": "m3 s-1",
                }
            )
        store.write_budgets(sim_id, records)


__all__ = ["LinearReservoirExtractor"]
