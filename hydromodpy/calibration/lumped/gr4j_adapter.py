"""Calibration-side adapter for the lumped GR4J catchment model.

GR4J runs in-memory through ``simulation.extraction.calibration_bridge``: it
never writes solver binaries, and ``execute`` is therefore not wired into the
staged flow runner. The class exposes ``extract_observables`` so the
calibration engine can read the catalogued series back from the cold-path
``store`` after ``promote_trial`` has persisted the best run, using the same
contract as the MODFLOW backend adapters.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    require_unique_request_ids,
)
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.observables import series_observable

GR4J_SERIES_UNITS: dict[str, str] = {"discharge": "m3/s", "storage": "mm"}
"""Unit of every series GR4J publishes, the ones ``Gr4jFlowExtractor`` writes.

Neither the RAM cache nor the catalog query hands the unit back, so it is
restated here rather than left empty: an observable whose unit is the empty
string cannot be checked by the cost that reads it.
"""


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

    def extract_observables(
        self,
        ctx: RunContext,
        store: Any,
        requests: Sequence[ObservableRequest],
        *,
        time_index: pd.DatetimeIndex | None = None,
    ) -> dict[str, ObservableResult]:
        """Read the requested series from RAM or from the cold store.

        Two paths are supported:

        - **Lightweight (``store=None``)**: read the series the GR4J runner
          stashed in the per-trial :class:`LumpedRamCache`. This skips every
          DuckDB / Parquet write so calibration trials stay strictly in memory.
        - **Cold (``store`` non-None)**: query the ``Catalog``.
          ``promote_trial`` writes the best GR4J trial under
          ``station_id="outlet"`` (or the id carried by the request ``key``)
          and this method reads it back for full-fidelity reporting.

        GR4J is lumped, so every observable sits on the ``domain`` support and
        the request ``key`` names the station when it is not the outlet.
        """
        require_unique_request_ids(requests)
        served: dict[str, ObservableResult] = {}
        for request in requests:
            if request.support != "domain":
                raise ObservableNotAvailableError(
                    f"GR4J is lumped: it has no {request.support!r} support, only 'domain'."
                )
            units = GR4J_SERIES_UNITS.get(request.name)
            if units is None:
                raise ObservableNotAvailableError(
                    f"GR4J declares no unit for {request.name!r}; it publishes "
                    f"{sorted(GR4J_SERIES_UNITS)}. Serving the series unitless would let a "
                    "cost threshold it without being able to check what it received."
                )
            series = self._read_series(
                ctx,
                store,
                station_id=request.key or "outlet",
                variable=request.name,
                time_index=time_index,
            )
            served[request.id] = series_observable(request, series, units=units)
        return served

    def _read_series(
        self,
        ctx: RunContext,
        store: Any,
        *,
        station_id: str,
        variable: str,
        time_index: pd.DatetimeIndex | None,
    ) -> pd.Series:
        """Return one GR4J series, from the RAM cache or from the catalog."""
        if store is None:
            from hydromodpy.calibration.lumped.ram_cache import load_series

            execution = getattr(getattr(ctx, "state", None), "execution", None)
            if execution is None:
                raise NotImplementedError(
                    "GR4J lightweight calibration extraction requires a trial "
                    "context that exposes execution state."
                )
            series = load_series(execution, station_id, variable)
            if series is None or getattr(series, "empty", True):
                raise KeyError(
                    f"No GR4J RAM-cached series for station={station_id!r}, "
                    f"variable={variable!r}. Did the trial stash its outputs?"
                )
            if time_index is not None and len(time_index) == len(series):
                return pd.Series(series.values, index=time_index, name=variable)
            return pd.Series(series.values, name=variable)

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


__all__ = ["GR4J_SERIES_UNITS", "Gr4jAdapter"]
