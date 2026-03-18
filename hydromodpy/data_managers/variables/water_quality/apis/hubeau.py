"""Hub'Eau water quality API adapter.

Endpoints:
- River: /api/v2/qualite_rivieres/analyse_pc
- Groundwater: /api/v1/qualite_nappes/analyses

Each station may have multiple parameters (pH, nitrates, etc.).
One PointRecord is produced per (station, parameter) pair.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Mapping

import pandas as pd

from hydromodpy.data_managers.common.api_helpers import get_json

logger = logging.getLogger(__name__)
from hydromodpy.data_managers.contracts.location import StationLocation
from hydromodpy.data_managers.contracts.timeseries import PointRecord

API_RIVER_URL = "https://hubeau.eaufrance.fr/api/v2/qualite_rivieres/analyse_pc"
API_PZ_URL = "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/analyses"
API_RIVER_STATIONS = "https://hubeau.eaufrance.fr/api/v2/qualite_rivieres/station_pc"
API_PZ_STATIONS = "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/stations"


def fetch(
    *,
    site_type: str = "river",
    bbox: tuple[float, float, float, float] | None = None,
    station_ids: list[str] | None = None,
    date_start: datetime,
    date_end: datetime,
    parameters: list[str] | None = None,
    nearest_to: tuple[float, float] | None = None,
    fallback_search_radius_km: float | None = None,
) -> list[PointRecord]:
    """Fetch water quality data from Hub'Eau.

    Returns one PointRecord per (station, parameter) combination.

    Parameters
    ----------
    nearest_to : tuple | None
        ``(lon, lat)`` to keep only the nearest station.
    fallback_search_radius_km : float | None
        If no station found in bbox, expand by this radius and retry.
    """
    is_river = site_type.startswith("river")

    if station_ids is None:
        if bbox is None:
            raise ValueError("Either station_ids or bbox required.")
        station_ids = _discover_stations(bbox, is_river=is_river)
        if not station_ids and fallback_search_radius_km:
            from hydromodpy.data_managers.common.geo_helpers import expand_bbox
            expanded = expand_bbox(bbox, fallback_search_radius_km)
            logger.info("Hub'Eau WQ: no stations in bbox, expanding by %s km", fallback_search_radius_km)
            station_ids = _discover_stations(expanded, is_river=is_river)
        if not station_ids:
            logger.info("Hub'Eau WQ: no stations in bbox")
            return []

    # nearest_to: keep only the closest station to the target point
    if nearest_to and station_ids:
        station_ids = _keep_nearest(station_ids, nearest_to, is_river=is_river)
        if not station_ids:
            logger.info("Hub'Eau WQ: no station with coordinates for nearest selection.")
            return []

    logger.info("Hub'Eau WQ (%s): %d stations", site_type, len(station_ids))
    records: list[PointRecord] = []

    for sid in station_ids:
        location = _fetch_station_location(sid, is_river=is_river)
        raw_df = _download_analyses(sid, date_start=date_start, date_end=date_end, is_river=is_river)
        if raw_df.empty:
            logger.info("  %s: no data", sid)
            continue

        if location is None:
            location = _extract_location_from_data(sid, raw_df)

        df = _normalize_dataframe(raw_df, is_river=is_river)
        if df.empty:
            continue

        # Filter to requested parameters
        if parameters is not None:
            lower_params = [p.lower() for p in parameters]
            df = df[df["parameter"].str.lower().isin(lower_params)]
            if df.empty:
                continue

        # One PointRecord per parameter
        for param_name, param_df in df.groupby("parameter"):
            ts = param_df[["datetime", "value"]].sort_values("datetime").reset_index(drop=True)
            if ts.empty:
                continue
            unit = param_df["unit"].iloc[0] if "unit" in param_df.columns else ""
            records.append(
                PointRecord(
                    station_id=sid, variable=str(param_name), source="hubeau",
                    unit=str(unit) if pd.notna(unit) else "",
                    frequency="irregular", data=ts,
                    date_start=ts["datetime"].min().to_pydatetime(),
                    date_end=ts["datetime"].max().to_pydatetime(),
                    location=location,
                )
            )

        n_params = len(set(df["parameter"]))
        logger.info("  %s: %d analyses, %d parameters", sid, len(df), n_params)

    logger.info("Hub'Eau WQ: %d total records", len(records))
    return records


def _keep_nearest(
    ids: list[str],
    nearest_to: tuple[float, float],
    *,
    is_river: bool,
) -> list[str]:
    """Keep only the station closest to *nearest_to* ``(lon, lat)``."""
    from hydromodpy.data_managers.common.geo_helpers import haversine_km

    target_lon, target_lat = nearest_to
    best_id: str | None = None
    best_dist = float("inf")

    for sid in ids:
        loc = _fetch_station_location(sid, is_river=is_river)
        if loc is None:
            continue
        dist = haversine_km(target_lon, target_lat, loc.x, loc.y)
        if dist < best_dist:
            best_dist = dist
            best_id = sid

    if best_id is None:
        return []
    logger.info("Hub'Eau WQ: nearest to (%.4f, %.4f) → %s (%.1f km)", target_lon, target_lat, best_id, best_dist)
    return [best_id]


def _discover_stations(bbox: tuple, *, is_river: bool, max_stations: int = 50) -> list[str]:
    """Find station IDs inside bbox."""
    url = API_RIVER_STATIONS if is_river else API_PZ_STATIONS
    params = {
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "size": min(max_stations, 10000),
        "format": "json",
    }
    payload = get_json(url, params=params)
    if payload is None:
        return []

    seen: set[str] = set()
    ids: list[str] = []
    for row in payload.get("data", []):
        sid = str(row.get("code_station" if is_river else "code_bss", "")
                  or row.get("bss_id", "")).strip()
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)
        if len(ids) >= max_stations:
            break
    return ids


def _fetch_station_location(station_id: str, *, is_river: bool) -> StationLocation | None:
    """Get station coordinates from stations endpoint."""
    url = API_RIVER_STATIONS if is_river else API_PZ_STATIONS
    if is_river:
        params = {"code_station": station_id, "size": 1, "format": "json"}
    elif "/" in station_id:
        params = {"code_bss": station_id, "size": 1, "format": "json"}
    else:
        params = {"bss_id": station_id, "size": 1, "format": "json"}

    payload = get_json(url, params=params)
    if not payload or not payload.get("data"):
        return None

    row = payload["data"][0]
    x = row.get("longitude") or row.get("longitude_station")
    y = row.get("latitude") or row.get("latitude_station")

    # Fallback: geometry object
    if x is None or y is None:
        geom = row.get("geometry")
        if isinstance(geom, Mapping):
            coords = geom.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                x = x or coords[0]
                y = y or coords[1]

    if x is None or y is None:
        return None

    name = row.get("libelle_station") or row.get("nom_station") or station_id
    return StationLocation(id=station_id, x=float(x), y=float(y), crs="EPSG:4326",
                           metadata={"name": name})


def _extract_location_from_data(station_id: str, df: pd.DataFrame) -> StationLocation | None:
    """Try to get coordinates from analysis records."""
    for _, row in df.head(5).iterrows():
        x, y = row.get("longitude"), row.get("latitude")
        if pd.notna(x) and pd.notna(y):
            return StationLocation(id=station_id, x=float(x), y=float(y), crs="EPSG:4326")
    return None


def _download_analyses(
    station_id: str, *, date_start: datetime, date_end: datetime, is_river: bool,
) -> pd.DataFrame:
    """Download analyses year by year."""
    url = API_RIVER_URL if is_river else API_PZ_URL
    all_records: list[dict] = []

    for year in range(date_start.year, date_end.year + 1):
        year_start = max(date_start, datetime(year, 1, 1))
        year_end = min(date_end, datetime(year, 12, 31))

        params: dict = {"size": 20000, "format": "json"}
        if is_river:
            params["code_station"] = station_id
        elif "/" in station_id:
            params["code_bss"] = station_id
        else:
            params["bss_id"] = station_id
        params["date_debut_prelevement"] = year_start.strftime("%Y-%m-%d")
        params["date_fin_prelevement"] = year_end.strftime("%Y-%m-%d")

        payload = get_json(url, params=params)
        if payload is not None:
            all_records.extend(payload.get("data", []))

    return pd.DataFrame(all_records) if all_records else pd.DataFrame()


def _normalize_dataframe(df: pd.DataFrame, *, is_river: bool) -> pd.DataFrame:
    """Normalize raw API output to columns [datetime, parameter, value, unit]."""
    out = pd.DataFrame()

    # Date
    for col in ("date_prelevement", "date_debut_prelevement", "date"):
        if col in df.columns:
            out["datetime"] = pd.to_datetime(df[col], errors="coerce")
            break
    else:
        return pd.DataFrame()

    # Parameter name
    if is_river:
        out["parameter"] = df.get("libelle_parametre", pd.Series(dtype=str))
    else:
        out["parameter"] = df.get("nom_param", df.get("libelle_parametre", pd.Series(dtype=str)))

    # Value
    for col in ("resultat", "valeur"):
        if col in df.columns:
            out["value"] = pd.to_numeric(df[col], errors="coerce")
            break
    else:
        return pd.DataFrame()

    # Unit
    for col in ("symbole_unite", "nom_unite", "unite"):
        if col in df.columns:
            out["unit"] = df[col]
            break
    else:
        out["unit"] = ""

    return out.dropna(subset=["datetime", "value"]).reset_index(drop=True)
