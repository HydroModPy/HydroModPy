"""SHOM tide gauge API client for sea-level data.

Downloads sea-level observations from the Service Hydrographique et
Oceanographique de la Marine (SHOM) API.  Stateless — no class state,
returns ``list[PointRecord]``.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from hydromodpy.data.common.progress import log_step
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

API_BASE = "https://services.data.shom.fr/maregraphie"


def fetch(
    *,
    geographic: object,
    date_start: datetime,
    date_end: datetime,
    nearest: bool = True,
    fallback_search_radius_km: float | None = None,
    write: bool = True,
) -> list[PointRecord]:
    """Download sea-level data from the nearest SHOM tide gauge.

    Parameters
    ----------
    geographic
        Watershed object with ``centroid_long_lat`` attribute.
    date_start, date_end
        Date range for the download.
    nearest
        If True, find the nearest tide gauge to the watershed centroid.
    fallback_search_radius_km
        Maximum distance (km) for nearest gauge search.  None = unlimited.
    write
        If True, cache downloaded data to CSV in the solver scratch folder.

    Returns
    -------
    list[PointRecord]
        A single PointRecord with the sea-level time series.
    """
    session = requests.Session()
    try:
        # 1. Discover tide gauges
        gauges = _discover_tide_gauges(session)

        # 2. Find nearest
        tg_id, tg_name, tg_lat, tg_lon = _find_nearest(
            geographic, gauges, radius_km=fallback_search_radius_km,
        )

        # 3. Check for cached data
        cached_df = _try_load_cached(geographic, tg_id, date_start, date_end)
        if cached_df is not None:
            df = cached_df
        else:
            # 4. Get vertical reference
            zh_ref = _get_vertical_reference(session, tg_id)

            # 5. Download sea-level data (chunked 31-day windows)
            df = _download_sea_level(session, tg_id, date_start, date_end, zh_ref)

            # 6. Optionally write cache
            if write:
                _write_cache(geographic, tg_id, date_start, date_end, df)
    finally:
        session.close()

    if df.empty:
        logger.info("SHOM: no data returned for tide gauge %s (%s)", tg_name, tg_id)
        return []

    ts_data = pd.DataFrame({
        "datetime": pd.to_datetime(df["timestamp"]),
        "value": df["value"].astype(float),
    })

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


def _find_nearest(
    geographic: object,
    gauges: pd.DataFrame,
    *,
    radius_km: float | None = None,
) -> tuple[str, str, float, float]:
    """Find the nearest tide gauge to the watershed centroid."""
    centroid = geographic.centroid_long_lat
    gauges = gauges.copy()
    gauges["_dist"] = np.sqrt(
        (gauges["longitude"] - centroid[1]) ** 2
        + (gauges["latitude"] - centroid[0]) ** 2
    )

    if radius_km is not None:
        # Approximate degree-to-km conversion for filtering
        max_deg = radius_km / 111.0
        gauges = gauges[gauges["_dist"] <= max_deg]
        if gauges.empty:
            raise ValueError(
                f"No SHOM tide gauge found within {radius_km} km of centroid."
            )

    closest = gauges.loc[gauges["_dist"].idxmin()]
    tg_id = str(closest["shom_id"])
    tg_name = str(closest.get("name", tg_id))
    tg_lat = float(closest["latitude"])
    tg_lon = float(closest["longitude"])
    log_step("SHOM: nearest tide gauge: %s (%s) at (%.4f, %.4f)" % (tg_name, tg_id, tg_lat, tg_lon))
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

    current = date_start
    while current <= date_end:
        chunk_end = min(current + timedelta(days=31), date_end)
        dt_start = f'{current.strftime("%Y-%m-%d")}T00%3A00%3A00Z'
        dt_end = f'{chunk_end.strftime("%Y-%m-%d")}T00%3A00%3A00Z'
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

    if not chunks:
        return pd.DataFrame(columns=["timestamp", "value"])

    df = pd.concat(chunks, ignore_index=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["value"] = df["value"] + zh_ref
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df[df["timestamp"] <= date_end]
    return df


def _try_load_cached(
    geographic: object,
    tg_id: str,
    date_start: datetime,
    date_end: datetime,
) -> pd.DataFrame | None:
    """Try to load previously downloaded SHOM data from local cache."""
    stable_folder = getattr(geographic, "stable_folder", None)
    if stable_folder is None:
        return None
    output_folder = os.path.join(stable_folder, "oceanic")
    start_str = date_start.strftime("%Y%m%d")
    end_str = date_end.strftime("%Y%m%d")
    filename = f"sealevel_shom_{tg_id}_{start_str}_{end_str}_H.csv"
    filepath = os.path.join(output_folder, filename)
    if os.path.exists(filepath):
        log_step("SHOM: cache hit %s" % filename)
        return pd.read_csv(filepath, parse_dates=["timestamp"])
    return None


def _write_cache(
    geographic: object,
    tg_id: str,
    date_start: datetime,
    date_end: datetime,
    df: pd.DataFrame,
) -> None:
    """Write downloaded SHOM data to local cache."""
    stable_folder = getattr(geographic, "stable_folder", None)
    if stable_folder is None:
        return
    output_folder = os.path.join(stable_folder, "oceanic")
    os.makedirs(output_folder, exist_ok=True)
    start_str = date_start.strftime("%Y%m%d")
    end_str = date_end.strftime("%Y%m%d")
    filename = f"sealevel_shom_{tg_id}_{start_str}_{end_str}_H.csv"
    filepath = os.path.join(output_folder, filename)
    df.to_csv(filepath, index=False)
    log_step("SHOM: cached data to %s" % filename)
