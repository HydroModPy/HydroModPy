"""Export the series and the budget of a run to CSV files.

Times are written as naive ISO text on the run's clock, ``2002-10-01 00:00:00``:
the catalog stores them in UTC, and a session zone never shifts them. A
spreadsheet reads the file as the run wrote it.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    import duckdb

logger = get_logger(__name__)

OBSERVED_SUFFIX = "_obs"
"""The suffix of an observed series, stored beside the simulated one."""

EXPORTED_STATION_NAMES: dict[str, str] = {"_catchment": "catchment"}
"""Internal station ids and the name an exported file gives them.

``_catchment`` is the station the whole-catchment simulated series are stored
under (``simulation/extraction/derivation/catchment_aggregation.py``). The
leading underscore marks it internal; next to a real gauge code in a
spreadsheet it reads as a broken join."""

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

Window = tuple[Any, Any]
"""A ``(start, end)`` pair of naive timestamps on the run clock."""


def _station_expression() -> tuple[str, list[str]]:
    """Return the SQL that renames the internal station ids, and its parameters."""
    if not EXPORTED_STATION_NAMES:
        return "station_id", []
    cases = " ".join("WHEN station_id = ? THEN ?" for _ in EXPORTED_STATION_NAMES)
    params = [item for pair in EXPORTED_STATION_NAMES.items() for item in pair]
    return f"CASE {cases} ELSE station_id END", params


def _window_filter(windows: Sequence[Window]) -> tuple[str, list[Any]]:
    """Return the SQL keeping the rows of a series inside ``windows``.

    A simulated value is stamped at the end of its period, so a window keeps
    ``(start, end]``. An observation is stamped when it was taken, so a window
    keeps ``[start, end)``. Each keeps what falls in the periods of the window.
    No window keeps no row, as an empty ``variables`` list does.
    """
    if not windows:
        return "FALSE", []
    clock = "timezone('UTC', time)"
    clauses: list[str] = []
    params: list[Any] = []
    for start, end in windows:
        clauses.append(
            f"((ends_with(variable, ?) AND {clock} >= ? AND {clock} < ?) "
            f"OR (NOT ends_with(variable, ?) AND {clock} > ? AND {clock} <= ?))"
        )
        start_ts = pd.Timestamp(start).to_pydatetime()
        end_ts = pd.Timestamp(end).to_pydatetime()
        params.extend([OBSERVED_SUFFIX, start_ts, end_ts, OBSERVED_SUFFIX, start_ts, end_ts])
    return "(" + " OR ".join(clauses) + ")", params


def export_csv(
    conn: duckdb.DuckDBPyConnection,
    sim_id: str,
    output_path: str | Path,
    *,
    station_id: str | None = None,
    variables: Sequence[str] | None = None,
    windows: Sequence[Window] | None = None,
) -> Path:
    """Export the series of a simulation to a CSV file.

    The rows stream from DuckDB straight to disk through ``COPY``. Columns are
    ``datetime, station_id, variable, value, unit``, one row per value.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        Open connection to the project index database.
    sim_id : str
        Simulation UUID.
    output_path : str or Path
        Destination ``.csv`` file.
    station_id : str, optional
        Keep one station. ``None`` keeps them all.
    variables : sequence of str, optional
        Keep these variables. ``None`` keeps them all.
    windows : sequence of (start, end), optional
        Keep the rows inside these windows of the run clock, naive
        timestamps. ``None`` keeps every row, the observations before and
        after the simulation included.

    Returns
    -------
    Path
        The written file path.

    Examples
    --------
    >>> export_csv(
    ...     catalog.connection, run.sim_id, "discharge.csv", variables=["discharge"]
    ... )  # doctest: +SKIP
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    station_sql, station_params = _station_expression()
    params: list[Any] = [*station_params, sim_id]
    filters = ["sim_id = ?"]
    if station_id is not None:
        filters.append("station_id = ?")
        params.append(station_id)
    if variables is not None:
        names = list(variables)
        if not names:
            filters.append("FALSE")
        else:
            filters.append(f"variable IN ({', '.join('?' for _ in names)})")
            params.extend(names)
    if windows is not None:
        clause, window_params = _window_filter(windows)
        filters.append(clause)
        params.extend(window_params)

    target = str(output_path).replace("'", "''")
    query = (
        "COPY ("
        f"SELECT strftime(timezone('UTC', time), '{_TIME_FORMAT}') AS datetime, "
        f"{station_sql} AS station_id, variable, value, unit "
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


BUDGET_COLUMNS = (
    "period_start",
    "period_end",
    "timestep",
    "zone_id",
    "component",
    "flux_in",
    "flux_out",
    "unit",
)
"""The columns of a budget CSV. A budget is a flux over its period, so both ends are named."""


def export_budget_csv(
    budget: pd.DataFrame,
    output_path: str | Path,
    *,
    timesteps: Sequence[int] | None = None,
    edges: Sequence[Any] | None = None,
) -> Path:
    """Export the water budget rows of a run to a CSV file.

    Parameters
    ----------
    budget : pandas.DataFrame
        The ``budgets`` rows of one run, as ``Run.budget()`` returns them.
    output_path : str or Path
        Destination ``.csv`` file.
    timesteps : sequence of int, optional
        Keep these periods. ``None`` keeps them all.
    edges : sequence of timestamps, optional
        The ``n + 1`` period edges of the run. Each row then names the start
        and the end of its period; without them both columns stay empty.

    Returns
    -------
    Path
        The written file path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = budget.copy()
    if timesteps is not None:
        frame = frame[frame["timestep"].isin([int(step) for step in timesteps])]
    steps = frame["timestep"].astype(int).to_numpy()
    if edges is not None and len(edges) > 1:
        index = pd.DatetimeIndex(edges)
        frame["period_start"] = index[steps].strftime(_TIME_FORMAT)
        frame["period_end"] = index[steps + 1].strftime(_TIME_FORMAT)
    else:
        frame["period_start"] = ""
        frame["period_end"] = ""
    for column in BUDGET_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    frame = frame.sort_values(["timestep", "zone_id", "component"], kind="stable")
    frame.loc[:, list(BUDGET_COLUMNS)].to_csv(output_path, index=False)
    logger.info("Exported budget CSV: %s (%d rows)", output_path, len(frame))
    return output_path
