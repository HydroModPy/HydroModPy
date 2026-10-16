"""Export the series and the budget of a run to CSV files.

Times are written as naive ISO text on the run's clock, ``2002-10-01 00:00:00``:
the catalog stores them in UTC, and a session zone never shifts them. A
spreadsheet reads the file as the run wrote it.

Every row starts with the ``site`` and the ``case_id`` of the run, so rows of
several runs concatenated still say where each one comes from. The full
identity block goes to the ``.meta.json`` sidecar the caller writes.

The series are read from the ``timeseries`` payload of the run directory
(``tables.parquet/timeseries.parquet``), never from the project index: a run
exports what its own directory holds.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.results.identity import Identity

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

IDENTITY_COLUMNS = ("site", "case_id")
"""The columns every exported row starts with: where the row comes from."""


def _identity_values(identity: Identity) -> tuple[str, str]:
    """Return the ``site`` and ``case_id`` a row carries; the case stands for a run without site."""
    return (identity.site or identity.case_id, identity.case_id)


SERIES_COLUMNS = (*IDENTITY_COLUMNS, "datetime", "station_id", "variable", "value", "unit")
"""The columns of a series CSV, one row per value."""


def _in_windows(frame: pd.DataFrame, windows: Sequence[Window]) -> pd.Series:
    """Return the mask of the rows of a series inside ``windows``.

    A simulated value is stamped at the end of its period, so a window keeps
    ``(start, end]``. An observation is stamped when it was taken, so a window
    keeps ``[start, end)``. Each keeps what falls in the periods of the window.
    No window keeps no row, as an empty ``variables`` list does.
    """
    keep = pd.Series(False, index=frame.index)
    observed = frame["variable"].str.endswith(OBSERVED_SUFFIX)
    clock = frame["_clock"]
    for start, end in windows:
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        keep |= (observed & (clock >= lo) & (clock < hi)) | (
            ~observed & (clock > lo) & (clock <= hi)
        )
    return keep


def export_csv(
    timeseries_path: str | Path,
    sim_id: str,
    output_path: str | Path,
    *,
    identity: Identity,
    station_id: str | None = None,
    variables: Sequence[str] | None = None,
    windows: Sequence[Window] | None = None,
) -> Path:
    """Export the series of a simulation to a CSV file.

    Columns are ``site, case_id, datetime, station_id, variable, value,
    unit``, one row per value, ordered by station, variable and step.

    Parameters
    ----------
    timeseries_path : str or Path
        The ``timeseries`` Parquet payload of the run. A run without one
        writes the header only.
    sim_id : str
        Simulation UUID.
    output_path : str or Path
        Destination ``.csv`` file.
    identity : Identity
        The identity block of the run: its site and case start every row.
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
    ...     run_dir / "tables.parquet" / "timeseries.parquet",
    ...     run.sim_id,
    ...     "discharge.csv",
    ...     identity=identity,
    ...     variables=["discharge"],
    ... )  # doctest: +SKIP
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frame = _read_series(Path(timeseries_path), sim_id)
    if station_id is not None:
        frame = frame[frame["station_id"] == station_id]
    if variables is not None:
        frame = frame[frame["variable"].isin(list(variables))]
    if windows is not None:
        frame = frame[_in_windows(frame, windows)]
    frame = frame.assign(station_id=frame["station_id"].replace(EXPORTED_STATION_NAMES))
    frame = frame.sort_values(["station_id", "variable", "timestep"], kind="stable")
    frame = frame.assign(datetime=frame["_clock"].dt.strftime(_TIME_FORMAT))
    frame["site"], frame["case_id"] = _identity_values(identity)
    frame.loc[:, list(SERIES_COLUMNS)].to_csv(output_path, index=False)
    if len(frame):
        logger.info("Exported CSV: %s (%d rows)", output_path, len(frame))
    else:
        logger.debug("No timeseries found for sim=%s", sim_id)
    return output_path


def _read_series(path: Path, sim_id: str) -> pd.DataFrame:
    """Return the rows of one run from its ``timeseries`` payload, times on the UTC clock.

    ``_clock`` holds each time as a naive UTC timestamp, the run clock. A run
    without a payload has no row.
    """
    columns = ["sim_id", "station_id", "variable", "timestep", "time", "value", "unit"]
    if path.is_file():
        frame = pd.read_parquet(path, columns=columns)
        frame = frame[frame["sim_id"] == sim_id].copy()
    else:
        frame = pd.DataFrame({column: pd.Series(dtype=object) for column in columns})
    times = pd.to_datetime(frame["time"], utc=True)
    frame["_clock"] = times.dt.tz_convert("UTC").dt.tz_localize(None)
    return frame


BUDGET_COLUMNS = (
    *IDENTITY_COLUMNS,
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
    identity: Identity,
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
    identity : Identity
        The identity block of the run: its site and case start every row.
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
    frame["site"], frame["case_id"] = _identity_values(identity)
    for column in BUDGET_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    frame = frame.sort_values(["timestep", "zone_id", "component"], kind="stable")
    frame.loc[:, list(BUDGET_COLUMNS)].to_csv(output_path, index=False)
    logger.info("Exported budget CSV: %s (%d rows)", output_path, len(frame))
    return output_path
