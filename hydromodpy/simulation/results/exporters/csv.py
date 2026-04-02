"""Export time series from DuckDB to CSV files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


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
        Open connection to ``project.duckdb``.
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

    query = "SELECT station_id, variable, timestamps, values, unit FROM timeseries WHERE sim_id = ?"
    params: list = [sim_id]

    if station_id is not None:
        query += " AND station_id = ?"
        params.append(station_id)
    if variable is not None:
        query += " AND variable = ?"
        params.append(variable)

    rows = conn.execute(query, params).fetchall()

    if not rows:
        logger.warning("No timeseries found for sim=%s", sim_id)
        pd.DataFrame(columns=["datetime", "station_id", "variable", "value", "unit"]).to_csv(
            output_path, index=False,
        )
        return output_path

    frames = []
    for sid, var, ts, vals, unit in rows:
        df = pd.DataFrame({
            "datetime": pd.DatetimeIndex(ts),
            "station_id": sid,
            "variable": var,
            "value": vals,
            "unit": unit or "",
        })
        frames.append(df)

    result = pd.concat(frames, ignore_index=True)
    result.sort_values(["station_id", "variable", "datetime"], inplace=True)
    result.to_csv(output_path, index=False)
    logger.info("Exported CSV: %s (%d rows)", output_path, len(result))
    return output_path
