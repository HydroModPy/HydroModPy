"""Output adapter for GR4J lumped model results."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from typing import Any

logger = logging.getLogger(__name__)


class GR4JOutputAdapter:
    """Inject GR4J in-memory results into a SimulationCatalog.

    GR4J is a lumped catchment model — results are already in memory
    as pandas Series (no binary files to parse). This adapter simply
    forwards them to the store's DuckDB tables.
    """

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
    ) -> None:
        """No-op: GR4J results are injected via write_from_memory."""
        pass

    def extract_from_memory(
        self,
        sim_id: str,
        store: Any,
        *,
        discharge: pd.Series | None = None,
        storage: pd.Series | None = None,
        extra: dict[str, pd.Series] | None = None,
        station_id: str = "outlet",
    ) -> None:
        """Write in-memory GR4J time series into the store.

        Parameters
        ----------
        sim_id : str
            Simulation UUID.
        store : SimulationCatalog
            Target store.
        discharge : pd.Series, optional
            Simulated discharge Q(t) at the outlet.
        storage : pd.Series, optional
            Internal storage S(t).
        extra : dict[str, pd.Series], optional
            Additional named time series to store.
        station_id : str
            Station label (default ``"outlet"``).
        """
        if discharge is not None:
            store.write_timeseries(sim_id, station_id, "discharge", discharge, unit="m3/s")
        if storage is not None:
            store.write_timeseries(sim_id, station_id, "storage", storage, unit="mm")
        if extra:
            for name, series in extra.items():
                store.write_timeseries(sim_id, station_id, name, series, unit="")

        logger.info("GR4J results written for sim %s", sim_id)

    def derive(
        self,
        sim_id: str,
        store: Any,
        config: dict | None = None,
    ) -> None:
        """No derived variables for lumped models."""
        pass
