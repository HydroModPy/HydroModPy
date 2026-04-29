"""Export time series from DuckDB to CSV files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry

if TYPE_CHECKING:
    import duckdb

logger = get_logger(__name__)


def export_csv(
    conn: duckdb.DuckDBPyConnection,
    sim_id: str,
    output_path: str | Path,
    *,
    station_id: str | None = None,
    variable: str | None = None,
) -> Path:
    """Export time series for a simulation to a CSV file.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        Open connection to ``hydromodpy.duckdb``.
    sim_id : str
        Simulation UUID.
    output_path : str or Path
        Destination ``.csv`` file.
    station_id : str, optional
        Filter by station. ``None`` exports all stations.
    variable : str, optional
        Filter by variable. ``None`` exports all variables.

    Returns
    -------
    Path
        The written file path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if variable is not None:
        field_registry.get(variable)

    query = "SELECT datetime, station_id, variable, value, unit FROM timeseries WHERE sim_id = ?"
    params: list = [sim_id]

    if station_id is not None:
        query += " AND station_id = ?"
        params.append(station_id)
    if variable is not None:
        query += " AND variable = ?"
        params.append(variable)

    query += " ORDER BY station_id, variable, datetime"

    result = conn.execute(query, params).fetchdf()

    if result.empty:
        logger.debug("No timeseries found for sim=%s", sim_id)
        pd.DataFrame(columns=["datetime", "station_id", "variable", "value", "unit"]).to_csv(
            output_path, index=False
        )
        return output_path

    result.to_csv(output_path, index=False)
    logger.info("Exported CSV: %s (%d rows)", output_path, len(result))
    return output_path
