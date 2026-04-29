"""Adapter for the ``flow/gr4j`` solver pair.

GR4J is a lumped catchment model run in-memory through
``simulation.extraction.calibration_bridge``: it never writes solver binaries,
and ``execute`` is therefore not wired into the staged flow runner. The class
exists so calibration can route through the same ``SolverAdapter`` Protocol
as MODFLOW backends (specifically ``extract_calibration_series``), which reads
the catalogued series back from the cold-path ``store`` after
``promote_trial`` has persisted the best run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult


class GR4JFlowAdapter:
    """GR4J flow adapter — calibration-only entry point."""

    process_type = "flow"
    solver_name = "gr4j"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: RunContext) -> None:
        """GR4J runs entirely in RAM; nothing to validate at the runner level."""

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """GR4J does not run through the staged flow runner.

        Calibration drives GR4J through ``make_hot_simulator`` /
        ``promote_trial`` instead of the ``ProcessRun`` lifecycle.
        """
        raise NotImplementedError(
            "GR4JFlowAdapter does not implement execute(); GR4J is driven by "
            "simulation.extraction.calibration_bridge.make_hot_simulator."
        )

    def cleanup(self, ctx: RunContext) -> None:
        """No scratch files to clean — GR4J keeps everything in RAM."""

    def extract_calibration_series(
        self,
        ctx: RunContext,
        store: Any,
        *,
        variable: str,
        station_cells: Mapping[str, tuple[int, int, int]] | None = None,
        time_index: pd.DatetimeIndex | None = None,
    ) -> pd.Series:
        """Read the simulated series for *variable* from the cold-path store.

        After calibration converges, ``promote_trial`` writes the best GR4J
        trial to the catalog under ``station_id="outlet"`` (or the station id
        provided via ``station_cells``). This method queries that timeseries
        back so downstream metric computation goes through the same Protocol
        as MODFLOW backends.
        """
        del ctx
        if store is None:
            return pd.Series(dtype=float, name=variable)
        station_id = "outlet"
        if station_cells:
            station_id = next(iter(station_cells))

        sim_id = self._latest_sim_id(store)
        if sim_id is None:
            return pd.Series(dtype=float, name=variable)
        try:
            ts = store.query_timeseries(sim_id, station_id, variable)
        except Exception:
            return pd.Series(dtype=float, name=variable)
        if ts is None or ts.empty:
            return pd.Series(dtype=float, name=variable)
        if time_index is not None and len(time_index) == len(ts):
            return pd.Series(ts.values, index=time_index, name=variable)
        return pd.Series(ts.values, name=variable)

    @staticmethod
    def _latest_sim_id(store: Any) -> str | None:
        """Return the most recent GR4J simulation id catalogued in *store*."""
        list_simulations = getattr(store, "list_simulations", None)
        if list_simulations is None:
            return None
        try:
            sims = list_simulations(solver="gr4j")
        except TypeError:
            sims = list_simulations()
        except Exception:
            return None
        if sims is None or getattr(sims, "empty", False):
            return None
        try:
            return str(sims.iloc[-1]["sim_id"])
        except Exception:
            return None


__all__ = ["GR4JFlowAdapter"]
