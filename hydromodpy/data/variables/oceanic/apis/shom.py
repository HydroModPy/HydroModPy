"""SHOM tide gauge API client for sea-level data.

Downloads sea-level observations from the Service Hydrographique et
Oceanographique de la Marine (SHOM) API. Stateless - no class state,
returns ``list[PointRecord]``.

Which gauge, and how it is named
--------------------------------
This was the last fetch function in the tree taking a ``geographic: object``,
and the port that F5b built left it unported for exactly that reason: its
selector is a point and not a box (``data/source/port.py:16``). The point is
now two named floats. It used to be one attribute called ``centroid_long_lat``
that held ``(lat, lon)`` -- ``Transformer.from_crs(crs, "epsg:4326")`` is built
without ``always_xy``, so it answers in the axis order EPSG:4326 declares,
which is latitude first. Every reader of that attribute compensated silently
and correctly, and the name said the opposite of what it held for as long as it
existed.

The gauge is either named outright or searched for, never both: ``station_id``
is the explicit answer and ``near_lat``/``near_lon`` the nearest-to-a-point
one. The flag that used to sit beside them, ``nearest``, was read by nobody --
``fetch`` accepted it and its body never mentioned it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from hydromodpy.core import progress
from hydromodpy.core.logging import get_logger
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord

logger = get_logger(__name__)

API_BASE = "https://services.data.shom.fr/maregraphie"


def fetch(
    *,
    date_start: datetime,
    date_end: datetime,
    station_id: str | None = None,
    near_lat: float | None = None,
    near_lon: float | None = None,
    fallback_search_radius_km: float | None = None,
    cache_dir: Path | None = None,
    write: bool = True,
) -> list[PointRecord]:
    """Download sea-level data from one SHOM tide gauge.

    Parameters
    ----------
    date_start, date_end
        Date range for the download.
    station_id
        SHOM identifier of the gauge to read. Mutually exclusive with the
        ``near_*`` pair.
    near_lat, near_lon
        WGS84 latitude and longitude of the point whose nearest gauge is read.
        Both or neither.
    fallback_search_radius_km
        Maximum distance (km) for the nearest-gauge search. None = unlimited.
    cache_dir
        Directory holding ``sealevel_shom_<id>_<start>_<end>_H.csv``. None
        disables the cache in both directions.
    write
        If True, cache the downloaded chronicle.

    Returns
    -------
    list[PointRecord]
        A single PointRecord with the sea-level time series.
    """
    has_point = near_lat is not None and near_lon is not None
    if (near_lat is None) != (near_lon is None):
        raise ValueError("SHOM needs both near_lat and near_lon, or neither.")
    if (station_id is None) == (not has_point):
        raise ValueError(
            "SHOM reads one gauge: name it with station_id, or give near_lat and "
            "near_lon to search for the nearest one. Not both, not neither."
        )

    session = requests.Session()
    try:
        gauges = _discover_tide_gauges(session)

        if station_id is not None:
            tg_id, tg_name, tg_lat, tg_lon = _gauge_by_id(gauges, station_id)
        else:
            tg_id, tg_name, tg_lat, tg_lon = _find_nearest(
                gauges,
                lat=float(near_lat),
                lon=float(near_lon),
                radius_km=fallback_search_radius_km,
            )

        cached_df = _try_load_cached(cache_dir, tg_id, date_start, date_end)
        if cached_df is not None:
            df = cached_df
        else:
            zh_ref = _get_vertical_reference(session, tg_id)
            df = _download_sea_level(session, tg_id, date_start, date_end, zh_ref)
            if write:
                _write_cache(cache_dir, tg_id, date_start, date_end, df)
    finally:
        session.close()

    if df.empty:
        logger.info("SHOM: no data returned for tide gauge %s (%s)", tg_name, tg_id)
        return []

    ts_data = pd.DataFrame(
        {
            "datetime": pd.to_datetime(df["timestamp"]),
            "value": df["value"].astype(float),
        }
    )

    location = StationLocation(
        id=str(tg_id),
        x=tg_lon,
        y=tg_lat,
        crs="EPSG:4326",
        metadata={"name": tg_name, "source": "shom"},
    )

    return [
        PointRecord(
            station_id=str(tg_id),
            variable="sea_level",
            source="shom",
            unit="m",
            frequency="H",
            data=ts_data,
            date_start=ts_data["datetime"].min().to_pydatetime(),
            date_end=ts_data["datetime"].max().to_pydatetime(),
            location=location,
        )
    ]


def _discover_tide_gauges(session: requests.Session) -> pd.DataFrame:
    """Fetch the list of SHOM tide gauge stations."""
    url = f"{API_BASE}/service/tidegauges"
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return pd.DataFrame(response.json())


def _gauge_by_id(gauges: pd.DataFrame, station_id: str) -> tuple[str, str, float, float]:
    """Read one gauge out of the discovered list, or say it is not there."""
    match = gauges[gauges["shom_id"].astype(str) == str(station_id)]
    if match.empty:
        raise ValueError(f"No SHOM tide gauge with id {station_id!r}.")
    row = match.iloc[0]
    return (
        str(row["shom_id"]),
        str(row.get("name", station_id)),
        float(row["latitude"]),
        float(row["longitude"]),
    )


def _find_nearest(
    gauges: pd.DataFrame,
    *,
    lat: float,
    lon: float,
    radius_km: float | None = None,
) -> tuple[str, str, float, float]:
    """Find the tide gauge nearest to a WGS84 point."""
    gauges = gauges.copy()
    gauges["_dist"] = np.sqrt((gauges["longitude"] - lon) ** 2 + (gauges["latitude"] - lat) ** 2)

    if radius_km is not None:
        # Approximate degree-to-km conversion for filtering
        max_deg = radius_km / 111.0
        gauges = gauges[gauges["_dist"] <= max_deg]
        if gauges.empty:
            raise ValueError(f"No SHOM tide gauge found within {radius_km} km of ({lat}, {lon}).")

    closest = gauges.loc[gauges["_dist"].idxmin()]
    tg_id = str(closest["shom_id"])
    tg_name = str(closest.get("name", tg_id))
    tg_lat = float(closest["latitude"])
    tg_lon = float(closest["longitude"])
    logger.debug(f"SHOM: nearest tide gauge: {tg_name} ({tg_id}) at ({tg_lat:.4f}, {tg_lon:.4f})")
    return tg_id, tg_name, tg_lat, tg_lon


def _get_vertical_reference(session: requests.Session, tg_id: str) -> float:
    """Get the vertical reference (zh_ref) for a tide gauge."""
    url = f"{API_BASE}/service/completetidegauge/{tg_id}"
    response = session.get(url, timeout=60)
    response.raise_for_status()
    info = response.json()
    return float(info["verticalRef"]["zh_ref"])


def _download_sea_level(
    session: requests.Session,
    tg_id: str,
    date_start: datetime,
    date_end: datetime,
    zh_ref: float,
) -> pd.DataFrame:
    """Download sea-level data in chunked 31-day windows."""
    sources = "3"  # hourly validated data
    interval = "60"  # minutes
    chunks: list[pd.DataFrame] = []

    total_chunks = (date_end - date_start).days // 32 + 1
    current = date_start
    with progress.task("Downloading SHOM sea level", total=total_chunks) as handle:
        while current <= date_end:
            chunk_end = min(current + timedelta(days=31), date_end)
            dt_start = f"{current.strftime('%Y-%m-%d')}T00%3A00%3A00Z"
            dt_end = f"{chunk_end.strftime('%Y-%m-%d')}T00%3A00%3A00Z"
            url = (
                f"{API_BASE}/observation/json/{tg_id}"
                f"?sources={sources}&dtStart={dt_start}&dtEnd={dt_end}&interval={interval}"
            )
            response = session.get(url, timeout=60)
            response.raise_for_status()
            data = response.json().get("data", [])
            if data:
                chunk_df = pd.DataFrame(data).reindex(columns=["timestamp", "value"])
                chunks.append(chunk_df[["timestamp", "value"]])
            current = chunk_end + timedelta(days=1)
            handle.advance()

    if not chunks:
        return pd.DataFrame(columns=["timestamp", "value"])

    df = pd.concat(chunks, ignore_index=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["value"] = df["value"] + zh_ref
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df[df["timestamp"] <= date_end]
    return df


def _cache_file(cache_dir: Path, tg_id: str, date_start: datetime, date_end: datetime) -> Path:
    start_str = date_start.strftime("%Y%m%d")
    end_str = date_end.strftime("%Y%m%d")
    return Path(cache_dir) / f"sealevel_shom_{tg_id}_{start_str}_{end_str}_H.csv"


def _try_load_cached(
    cache_dir: Path | None,
    tg_id: str,
    date_start: datetime,
    date_end: datetime,
) -> pd.DataFrame | None:
    """Try to load previously downloaded SHOM data from local cache."""
    if cache_dir is None:
        return None
    filepath = _cache_file(cache_dir, tg_id, date_start, date_end)
    if filepath.exists():
        logger.debug(f"SHOM: cache hit {filepath.name}")
        return pd.read_csv(filepath, parse_dates=["timestamp"])
    return None


def _write_cache(
    cache_dir: Path | None,
    tg_id: str,
    date_start: datetime,
    date_end: datetime,
    df: pd.DataFrame,
) -> None:
    """Write downloaded SHOM data to local cache."""
    if cache_dir is None:
        return
    filepath = _cache_file(cache_dir, tg_id, date_start, date_end)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(filepath, index=False)
    logger.debug(f"SHOM: cached data to {filepath.name}")
