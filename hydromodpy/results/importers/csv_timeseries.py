"""Read a CSV time series file produced by :mod:`hydromodpy.results.exporters.csv`.

Inverse of :func:`hydromodpy.results.exporters.csv.export_csv`. A simulated name is
validated against the series a solve writes
(:data:`~hydromodpy.results.exporters.vocabulary.SIMULATED_SERIES`) and the field
registry, so an unknown name fails fast with :class:`UnknownFieldError`. A measurement
keeps the name its provider gave it, a water-quality parameter for instance, so it is
not checked.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.core.exceptions import UnknownFieldError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import OBSERVED, SIMULATED, series_selector
from hydromodpy.results import field_registry
from hydromodpy.results.exporters.csv import SERIES_COLUMNS
from hydromodpy.results.exporters.vocabulary import SIMULATED_SERIES

logger = get_logger(__name__)


def _check_series(variable: str, source: str) -> None:
    """Refuse a series ``export_csv`` cannot have written."""
    if source == OBSERVED or variable in SIMULATED_SERIES or field_registry.has(variable):
        return
    raise UnknownFieldError(variable, (*SIMULATED_SERIES, *field_registry.all_names()))


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
        Keep only the rows of this series, by the name ``hmp.read`` and
        ``[[export]]`` read it: ``discharge``, or ``discharge_obs`` for the
        measurement. ``None`` keeps all the series of the file.

    Returns
    -------
    pandas.DataFrame
        Columns: ``site``, ``case_id``, ``datetime`` (timezone-aware UTC),
        ``station_id``, ``variable``, ``source``, ``value`` (float64), ``unit``. Empty
        when the input file contains only the header.
    """
    asked = None if variable is None else series_selector(variable)
    if asked is not None:
        _check_series(*asked)

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

    for name, source in df[["variable", "source"]].dropna().drop_duplicates().to_numpy():
        if source not in (SIMULATED, OBSERVED):
            raise ValueError(
                f"CSV {input_path}: source {source!r} of {name!r} is neither {SIMULATED!r} "
                f"nor {OBSERVED!r}. Write one of the two, as export_csv does."
            )
        _check_series(str(name), str(source))

    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df["value"] = df["value"].astype("float64")

    if station_id is not None:
        df = df[df["station_id"] == station_id]
    if asked is not None:
        df = df[(df["variable"] == asked[0]) & (df["source"] == asked[1])]

    df = df.reset_index(drop=True)
    logger.info("Imported CSV: %s (%d rows)", input_path, len(df))
    return df
