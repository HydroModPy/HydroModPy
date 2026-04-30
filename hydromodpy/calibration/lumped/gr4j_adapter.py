"""Calibration-side adapter for the lumped GR4J catchment model.

GR4J runs in-memory through ``simulation.extraction.calibration_bridge``: it
never writes solver binaries, and ``execute`` is therefore not wired into the
staged flow runner. The class exposes ``extract_calibration_series`` so the
calibration engine can read the catalogued series back from the cold-path
``store`` after ``promote_trial`` has persisted the best run, using the same
shape as the MODFLOW backend adapters.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult


class Gr4jAdapter:
    """GR4J calibration adapter (lumped model, no solver binary)."""

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
            "Gr4jAdapter does not implement execute(); GR4J is driven by "
            "simulation.extraction.calibration_bridge.make_hot_simulator."
        )

    def cleanup(self, ctx: RunContext) -> None:
        """No scratch files to clean: GR4J keeps everything in RAM."""

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
        back so downstream metric computation goes through the same shape as
        MODFLOW backends.
        """
        del ctx
        if store is None:
            raise NotImplementedError(
                "GR4J calibration extraction requires a catalog store; "
                "lightweight RAM extraction is not implemented."
            )
        station_id = "outlet"
        if station_cells:
            station_id = next(iter(station_cells))

        sim_id = self._latest_sim_id(store)
        if sim_id is None:
            raise KeyError("No GR4J simulation is available in the catalog store.")
        try:
            ts = store.query_timeseries(sim_id, station_id, variable)
        except Exception as exc:
            raise KeyError(
                f"No GR4J timeseries for station={station_id!r}, variable={variable!r}."
            ) from exc
        if ts is None or ts.empty:
            raise KeyError(
                f"Empty GR4J timeseries for station={station_id!r}, variable={variable!r}."
            )
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
        except Exception as exc:
            raise RuntimeError("Could not list GR4J simulations from the catalog store.") from exc
        if sims is None or getattr(sims, "empty", False):
            return None
        try:
            return str(sims.iloc[-1]["sim_id"])
        except Exception:
            return None


__all__ = ["Gr4jAdapter"]
