"""Export time series from DuckDB to CSV files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger

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

    The rows stream from DuckDB straight to disk through ``COPY``; a pandas
    round-trip spends most of its time formatting datetimes.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        Open connection to ``catalog.duckdb``.
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

    Examples
    --------
    >>> export_csv(
    ...     catalog.connection, run.sim_id, "discharge.csv", variable="discharge"
    ... )
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filters = ["sim_id = ?"]
    params: list = [sim_id]

    if station_id is not None:
        filters.append("station_id = ?")
        params.append(station_id)
    if variable is not None:
        filters.append("variable = ?")
        params.append(variable)

    # DuckDB renders whole-hour offsets as '+00'; pad to the '+00:00' form the
    # previous pandas export wrote.
    target = str(output_path).replace("'", "''")
    query = (
        "COPY ("
        "SELECT regexp_replace(CAST(time AS VARCHAR), '([+-][0-9]{2})$', '\\1:00') AS datetime, "
        "station_id, variable, value, unit "
        "FROM timeseries WHERE " + " AND ".join(filters) + " "
        "ORDER BY station_id, variable, timestep"
        f") TO '{target}' (FORMAT CSV, HEADER)"
    )
    row = conn.execute(query, params).fetchone()
    n_rows = int(row[0]) if row else 0
    if n_rows:
        logger.info("Exported CSV: %s (%d rows)", output_path, n_rows)
    else:
        logger.debug("No timeseries found for sim=%s", sim_id)
    return output_path
