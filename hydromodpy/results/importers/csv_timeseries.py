"""Read a CSV time series file produced by :mod:`hydromodpy.results.exporters.csv`.

Inverse of :func:`hydromodpy.results.exporters.csv.export_csv`. Variable names
present in the CSV are validated against :mod:`hydromodpy.results.field_registry`
so unknown fields fail fast with :class:`UnknownFieldError`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.exporters.csv import SERIES_COLUMNS

logger = get_logger(__name__)


def import_csv_timeseries(
    input_path: str | Path,
    *,
    station_id: str | None = None,
    variable: str | None = None,
) -> pd.DataFrame:
    """Read a time series CSV and return a typed :class:`pandas.DataFrame`.

    Parameters
    ----------
    input_path : str or Path
        Path to a ``.csv`` file written by :func:`export_csv`.
    station_id : str, optional
        Keep only rows for this station. ``None`` keeps all stations.
    variable : str, optional
        Keep only rows for this variable. The name is validated against the
        canonical field registry. ``None`` keeps all variables present in the
        file.

    Returns
    -------
    pandas.DataFrame
        Columns: ``site``, ``case_id``, ``datetime`` (timezone-aware UTC),
        ``station_id``, ``variable``, ``source``, ``value`` (float64), ``unit``. Empty
        when the input file contains only the header.
    """
    if variable is not None:
        field_registry.get(variable)

    input_path = Path(input_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"CSV time series not found: {input_path}")

    df = pd.read_csv(input_path)

    missing = [col for col in SERIES_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(
            f"CSV {input_path} is missing required columns: {missing}. "
            f"Expected: {list(SERIES_COLUMNS)}"
        )

    if df.empty:
        return df.astype(
            {
                "site": "object",
                "case_id": "object",
                "station_id": "object",
                "variable": "object",
                "source": "object",
                "value": "float64",
                "unit": "object",
            }
        )

    for name in df["variable"].dropna().unique():
        field_registry.get(str(name))

    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df["value"] = df["value"].astype("float64")

    if station_id is not None:
        df = df[df["station_id"] == station_id]
    if variable is not None:
        df = df[df["variable"] == variable]

    df = df.reset_index(drop=True)
    logger.info("Imported CSV: %s (%d rows)", input_path, len(df))
    return df
