"""Persist loaded observation timeseries into the simulation catalog.

Observation-type data managers (hydrometry, piezometry, intermittency,
water_quality) load station timeseries at project init time. This
extractor copies those series into the catalog's ``timeseries`` table
keyed by ``sim_id``, so they can be queried via
``Run.timeseries(variable, station=...)`` alongside the simulated ones.

To keep observed and simulated series distinguishable, observed
variables are written with an ``_obs`` suffix (e.g. ``discharge`` from
hydrometry becomes ``discharge_obs``). The forcing-reproducibility copy
in Zarr ``forcing/`` (written by :func:`step_persist_forcings`) is
separate and keeps the raw variable name.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


_OBSERVATION_FIELDS: tuple[str, ...] = (
    "hydrometry",
    "piezometry",
    "intermittency",
    "water_quality",
)


def ingest_observations(
    sim_id: str,
    store: Any,
    loaded_data: Any,
) -> int:
    """Write observation timeseries from ``loaded_data`` into the catalog.

    Iterates over observation-type fields on the ``LoadedDataContext``
    and writes each :class:`PointRecord` to the ``timeseries`` table.
    Observed variable names get an ``_obs`` suffix.

    Parameters
    ----------
    sim_id : str
        Simulation UUID.
    store : SimulationCatalog
        Open catalog.
    loaded_data : LoadedDataContext
        Project-level data context (``project._ctx.loaded_data``).

    Returns
    -------
    int
        Number of timeseries successfully persisted.
    """
    written = 0
    failures: list[str] = []
    for field in _OBSERVATION_FIELDS:
        result = getattr(loaded_data, field, None)
        if result is None:
            continue
        points = getattr(result, "points", None) or []
        for rec in points:
            try:
                ts = _point_to_series(rec)
                if ts is None or ts.empty:
                    continue
                _write_station(store, rec)
                store.write_timeseries(
                    sim_id,
                    station_id=str(rec.station_id),
                    variable=f"{rec.variable}_obs",
                    ts=ts,
                    unit=getattr(rec, "unit", "") or "",
                    qflag="observed",
                )
                store.write_observations(
                    station_id=str(rec.station_id),
                    variable_type=str(rec.variable),
                    ts=ts,
                    unit=getattr(rec, "unit", "") or "",
                    quality=_quality_value(getattr(rec, "quality", None)),
                )
                written += 1
            except Exception as exc:
                failures.append(f"{field}/{getattr(rec, 'station_id', '?')}: {exc}")
                logger.exception(
                    "Failed to ingest observation %s/%s",
                    field,
                    getattr(rec, "station_id", "?"),
                )
    if failures:
        raise RuntimeError("Observation ingestion failed: " + "; ".join(failures))
    if written:
        logger.info("Ingested %d observation timeseries for sim %s", written, sim_id)
    return written


def _quality_value(value: Any) -> str:
    if value is None:
        return "observed"
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _write_station(store: Any, rec: Any) -> None:
    writer = getattr(store, "write_station", None)
    if not callable(writer):
        return
    loc = getattr(rec, "location", None)
    metadata = {}
    if loc is not None and hasattr(loc, "to_dict"):
        metadata = loc.to_dict()
    writer(
        station_id=str(rec.station_id),
        variable_type=str(rec.variable),
        name=str(getattr(loc, "id", rec.station_id)),
        latitude=(float(loc.y) if loc is not None else None),
        longitude=(float(loc.x) if loc is not None else None),
        elevation=(float(metadata["z"]) if "z" in metadata else None),
        source=str(getattr(rec, "source", "")) or None,
        first_valid=getattr(rec, "date_start", None),
        last_valid=getattr(rec, "date_end", None),
        metadata=metadata,
    )


def _point_to_series(rec: Any) -> pd.Series | None:
    """Convert one ``PointRecord`` into a tz-naive ``pd.Series``."""
    df = getattr(rec, "data", None)
    if df is None or df.empty:
        return None
    idx = pd.to_datetime(df["datetime"])
    if idx.dt.tz is not None:
        idx = idx.dt.tz_localize(None)
    return pd.Series(
        df["value"].astype("float64").values,
        index=pd.DatetimeIndex(idx),
        name=f"{rec.variable}_obs",
    )
