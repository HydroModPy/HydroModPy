"""Hub'Eau Piézométrie API adapter.

Produces ``PointRecord`` instances from the Hub'Eau v1 niveaux_nappes endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

import pandas as pd
import requests

from hydromodpy.data.common.api_helpers import get_json
from hydromodpy.data.common.io_helpers import parse_datetime_column
from hydromodpy.data.common.progress import iter_progress, log_step
from hydromodpy.core.tools.log_manager import get_logger

logger = get_logger(__name__)
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord

API_BASE = "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes"

COVERAGE = {
    "country": "FR",
    "description": "Hub'Eau Piézométrie — piézomètres France métropolitaine",
    "variables": ["level", "depth"],
}


def fetch(
    *,
    product: str,
    bbox: tuple | None = None,
    station_ids: Sequence[str] | None = None,
    date_start: datetime,
    date_end: datetime,
    nearest_to: tuple[float, float] | None = None,
    require_observations: bool = True,
    fallback_search_radius_km: float | None = None,
) -> list[PointRecord]:
    """Fetch piezometry data from Hub'Eau.

    Parameters
    ----------
    product : str
        ``"level"`` or ``"depth"``.
    nearest_to : tuple | None
        ``(lon, lat)`` to find the nearest piezometer (even outside bbox).
    require_observations : bool
        Only keep piezometers with data overlapping the period.
    fallback_search_radius_km : float | None
        If no piezometer found in bbox, expand by this radius and retry.
    """
    if station_ids:
        ids = list(station_ids)
    elif bbox is not None:
        ids = _discover_piezometers_in_bbox(
            bbox, date_start=date_start, date_end=date_end,
            require_observations=require_observations,
        )
        if not ids and fallback_search_radius_km:
            from hydromodpy.data.common.geo_helpers import expand_bbox
            expanded = expand_bbox(bbox, fallback_search_radius_km)
            logger.info("Hub'Eau piezo: no piezometers in bbox, expanding by %s km", fallback_search_radius_km)
            ids = _discover_piezometers_in_bbox(
                expanded, date_start=date_start, date_end=date_end,
                require_observations=require_observations,
            )
    else:
        raise ValueError("Either bbox or station_ids must be provided.")

    # nearest_to: keep only the closest piezometer to the target point
    if nearest_to and ids:
        ids = _keep_nearest(ids, nearest_to)

    if not ids:
        logger.info("Hub'Eau piezo: no piezometers found.")
        return []

    log_step("Hub'Eau piezo: %d piezometers [%s -> %s]" % (len(ids), date_start.strftime("%Y-%m-%d"), date_end.strftime("%Y-%m-%d")))

    records: list[PointRecord] = []
    for bss_id in iter_progress(ids, desc="Piezometers"):
        location = _fetch_piezometer_location(bss_id)
        obs_df = _download_chronicles(bss_id, product, date_start, date_end)
        if obs_df.empty:
            continue

        records.append(
            PointRecord(
                station_id=bss_id,
                variable="groundwater_level" if product == "level" else "groundwater_depth",
                source="hubeau",
                unit="m",
                frequency="D",
                data=obs_df,
                date_start=date_start,
                date_end=date_end,
                location=location,
            )
        )

    log_step("Hub'Eau piezo: %d records loaded" % len(records))
    return records


# ---------------------------------------------------------------------------
# Nearest selection
# ---------------------------------------------------------------------------
def _keep_nearest(
    ids: list[str],
    nearest_to: tuple[float, float],
) -> list[str]:
    """Fetch locations for all candidates and keep only the closest one.

    Parameters
    ----------
    ids : list[str]
        Candidate BSS codes discovered in the bbox.
    nearest_to : tuple[float, float]
        ``(lon, lat)`` target point.
    """
    from hydromodpy.data.common.geo_helpers import haversine_km

    target_lon, target_lat = nearest_to
    best_id: str | None = None
    best_dist = float("inf")

    for bss_id in ids:
        loc = _fetch_piezometer_location(bss_id)
        if loc is None:
            continue
        dist = haversine_km(target_lon, target_lat, loc.x, loc.y)
        if dist < best_dist:
            best_dist = dist
            best_id = bss_id

    if best_id is None:
        return []
    logger.info("Hub'Eau piezo: nearest to (%.4f, %.4f) → %s (%.1f km)", target_lon, target_lat, best_id, best_dist)
    return [best_id]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _discover_piezometers_in_bbox(
    bbox: tuple,
    *,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    require_observations: bool = False,
) -> list[str]:
    """Find piezometer BSS codes inside bbox.

    If require_observations is True, filters out piezometers whose
    measurement period does not overlap with the requested dates.
    """
    xmin, ymin, xmax, ymax = bbox
    payload = get_json(
        f"{API_BASE}/stations",
        params={
            "bbox": f"{xmin},{ymin},{xmax},{ymax}",
            "size": 10_000,
            "format": "json",
        },
    )
    if payload is None:
        return []
    data = payload.get("data", [])

    ids: list[str] = []
    for row in data:
        bss = row.get("code_bss")
        if not bss:
            continue

        if require_observations and date_start and date_end:
            station_start = row.get("date_debut_mesure")
            station_end = row.get("date_fin_mesure")
            if not _station_period_overlaps(station_start, station_end, date_start, date_end):
                continue

        ids.append(str(bss))

    return ids


def _station_period_overlaps(
    station_start_str: str | None,
    station_end_str: str | None,
    req_start: datetime,
    req_end: datetime,
) -> bool:
    """Check if station measurement period overlaps with requested period."""
    if station_start_str:
        try:
            s_start = datetime.fromisoformat(station_start_str[:10])
            if s_start > req_end:
                return False
        except (ValueError, TypeError, requests.RequestException) as exc:
            logger.debug("Could not parse station start date %r: %s", station_start_str, exc)

    if station_end_str:
        try:
            s_end = datetime.fromisoformat(station_end_str[:10])
            if s_end < req_start:
                return False
        except (ValueError, TypeError, requests.RequestException) as exc:
            logger.debug("Could not parse station end date %r: %s", station_end_str, exc)

    return True


def _fetch_piezometer_location(bss_id: str) -> StationLocation | None:
    payload = get_json(
        f"{API_BASE}/stations",
        params={"code_bss": bss_id, "size": 1, "format": "json"},
    )
    if payload is None:
        return None
    data = payload.get("data", [])
    if not data:
        return None

    info = data[0]
    # Coordinates may be in geometry.coordinates or direct fields
    lon, lat = None, None
    geom = info.get("geometry")
    if isinstance(geom, dict):
        coords = geom.get("coordinates", [])
        if len(coords) >= 2:
            lon, lat = coords[0], coords[1]
    if lon is None:
        lon = info.get("longitude_station") or info.get("x")
    if lat is None:
        lat = info.get("latitude_station") or info.get("y")
    if lon is None or lat is None:
        return None

    return StationLocation(
        id=bss_id,
        x=float(lon),
        y=float(lat),
        crs="EPSG:4326",
        metadata={
            "station_name": info.get("nom_commune"),
            "altitude": info.get("altitude_station"),
            "depth_m": info.get("profondeur_investigation"),
            "start_date": info.get("date_debut_mesure"),
            "end_date": info.get("date_fin_mesure"),
        },
    )


# ---------------------------------------------------------------------------
# Chronicle download (by year to avoid API limits)
# ---------------------------------------------------------------------------
def _download_chronicles(
    bss_id: str,
    product: str,
    date_start: datetime,
    date_end: datetime,
) -> pd.DataFrame:
    all_records: list[dict] = []
    year = date_start.year
    while year <= date_end.year:
        y_start = max(date_start, datetime(year, 1, 1))
        y_end = min(date_end, datetime(year, 12, 31))
        payload = get_json(
            f"{API_BASE}/chroniques",
            params={
                "code_bss": bss_id,
                "date_debut_mesure": y_start.strftime("%Y-%m-%d"),
                "date_fin_mesure": y_end.strftime("%Y-%m-%d"),
                "size": 20_000,
                "format": "json",
            },
        )
        if payload:
            all_records.extend(payload.get("data", []))
        year += 1

    if not all_records:
        return pd.DataFrame(columns=["datetime", "value"])

    raw = pd.DataFrame(all_records)
    out = pd.DataFrame()

    # Datetime
    for col in ("date_mesure", "timestamp_mesure"):
        if col in raw.columns:
            out["datetime"] = parse_datetime_column(raw[col])
            break
    if "datetime" not in out.columns:
        return pd.DataFrame(columns=["datetime", "value"])

    # Value
    if product == "level" and "niveau_nappe_eau" in raw.columns:
        out["value"] = pd.to_numeric(raw["niveau_nappe_eau"], errors="coerce")
    elif product == "depth" and "profondeur_nappe" in raw.columns:
        out["value"] = pd.to_numeric(raw["profondeur_nappe"], errors="coerce")
    else:
        # Fallback: try both
        for col in ("niveau_nappe_eau", "profondeur_nappe"):
            if col in raw.columns:
                out["value"] = pd.to_numeric(raw[col], errors="coerce")
                break

    if "value" not in out.columns:
        return pd.DataFrame(columns=["datetime", "value"])

    out["quality"] = raw.get("qualification", "")
    out = out.dropna(subset=["datetime", "value"])
    return out.sort_values("datetime").reset_index(drop=True)
