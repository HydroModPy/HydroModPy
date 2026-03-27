"""Adapters bridging data_managers PointRecords to display functions.

These helpers extract and reshape observed data stored as ``list[PointRecord]``
into the DataFrames and series expected by plotting functions.  The goal is to
let the display layer depend ONLY on the standard contracts
(``PointRecord`` / ``StationLocation``) rather than legacy classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.data.contracts.timeseries import PointRecord


# ---------------------------------------------------------------------------
# Hydrometry (observed discharge)
# ---------------------------------------------------------------------------

def observed_discharge_series(
    records: list[PointRecord],
    *,
    station_id: str | None = None,
    freq: str = "ME",
    area_m2: float | None = None,
) -> pd.DataFrame | None:
    """Build an observed discharge time series from hydrometry PointRecords.

    Parameters
    ----------
    records : list[PointRecord]
        Hydrometry records (typically from HydrometryManager.load()).
    station_id : str, optional
        Pick a specific station.  If *None*, the first discharge record is used.
    freq : str
        Resampling frequency (default ``"ME"`` = monthly).
    area_m2 : float, optional
        Catchment area in m².  When provided the returned values are
        normalised to ``mm/<freq period>`` (useful for water-budget plots).
        When *None* the raw unit from the PointRecord is kept.

    Returns
    -------
    pd.DataFrame | None
        Single-column DataFrame (``"Q"``) with a datetime index, or *None*
        if no matching record was found.
    """
    if not records:
        return None

    # Select the record
    target = None
    for r in records:
        if station_id is not None and r.station_id != station_id:
            continue
        if r.variable in ("discharge", "streamflow"):
            target = r
            break
    if target is None:
        # Fall back to the first record regardless of variable name
        target = records[0] if station_id is None else None
    if target is None:
        return None

    df = target.data.copy()
    df = df.set_index("datetime").sort_index()
    series = df["value"].rename("Q")

    if area_m2 and area_m2 > 0:
        # Convert m³/s → mm over the resampled period
        # Q [m³/s] * 86400 [s/d] * 1000 [mm/m] / area_m2
        series = series * 86_400 * 1_000 / area_m2

    if freq:
        series = series.resample(freq).mean()

    return series.to_frame()


# ---------------------------------------------------------------------------
# Piezometry (observed groundwater levels)
# ---------------------------------------------------------------------------

def observed_piezometry_series(
    records: list[PointRecord],
    *,
    freq: str | None = None,
) -> pd.DataFrame | None:
    """Build observed piezometric levels from piezometry PointRecords.

    Parameters
    ----------
    records : list[PointRecord]
        Piezometry records (typically from PiezometryManager.load()).
    freq : str, optional
        Optional resampling frequency (e.g. ``"ME"`` for monthly).

    Returns
    -------
    pd.DataFrame | None
        DataFrame with a datetime index and one column per station
        (column name = station_id), or *None* if no records.
    """
    if not records:
        return None

    frames: list[pd.DataFrame] = []
    for r in records:
        df = r.data[["datetime", "value"]].copy()
        df = df.set_index("datetime").sort_index()
        df = df.rename(columns={"value": r.station_id})
        if freq:
            df = df.resample(freq).mean()
        frames.append(df)

    if not frames:
        return None

    merged = pd.concat(frames, axis=1).sort_index()
    return merged
