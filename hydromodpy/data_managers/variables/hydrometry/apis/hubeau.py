"""Hub'Eau Hydrométrie API adapter.

Produces ``PointRecord`` instances from the Hub'Eau v2 hydrometrie endpoints.
This adapter is self-contained: it manages its own HTTP calls via the
shared ``api_helpers`` module and converts raw JSON to the standard contract.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional, Sequence

import pandas as pd
import requests

from hydromodpy.data_managers.common.api_helpers import check_status, get_json
from hydromodpy.data_managers.common.progress import iter_progress, log_step
from hydromodpy.data_managers.contracts.location import StationLocation
from hydromodpy.support.tools.log_manager import get_logger

logger = get_logger(__name__)
from hydromodpy.data_managers.contracts.timeseries import PointRecord

API_BASE = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"

COVERAGE = {
    "country": "FR",
    "description": "Hub'Eau Hydrométrie — stations France métropolitaine",
    "variables": ["QmnJ", "QmM", "HmnJ", "QINM", "QINnJ", "QixM", "QIXnJ", "HIXM", "HIXnJ"],
    "frequency": ["D", "ME"],
}

# Hub'Eau discharge variables reported in L/s that we convert to m³/s
_DISCHARGE_VARS = {"QmnJ", "QmM", "QINM", "QINnJ", "QixM", "QIXnJ"}
_HEIGHT_VARS = {"HIXM", "HIXnJ"}
MAX_DAYS_PER_CHUNK = 20_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_station_id(raw_id: str) -> str:
    """Normalize a Hub'Eau station or site identifier to a 10-char station code.

    Hub'Eau uses 10-character station codes (``code_station``). Users sometimes
    provide the 8-character site code (``code_site``) instead.  When an 8-char
    code is given, ``"01"`` is appended (the default sensor suffix).
    """
    cleaned = str(raw_id).strip()
    if len(cleaned) == 8:
        return cleaned + "01"
    return cleaned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def fetch(
    *,
    product: str,
    bbox: tuple | None = None,
    station_ids: Sequence[str] | None = None,
    date_start: datetime,
    date_end: datetime,
    require_observations: bool = True,
    fallback_search_radius_km: float | None = None,
) -> list[PointRecord]:
    """Fetch hydrometry data from Hub'Eau and return ``PointRecord`` list.

    Either *bbox* or *station_ids* (or both) must be provided.
    If require_observations is True (default), stations without data
    in the period are filtered out during discovery.
    If no stations are found and fallback_search_radius_km is set,
    the bbox is expanded and discovery retried.
    """
    # Resolve station list
    if station_ids:
        ids = [_normalize_station_id(s) for s in station_ids]
    elif bbox is not None:
        ids = _discover_stations_in_bbox(
            bbox, date_start=date_start, date_end=date_end,
            require_observations=require_observations,
        )
        if not ids and fallback_search_radius_km:
            from hydromodpy.data_managers.common.geo_helpers import expand_bbox
            expanded = expand_bbox(bbox, fallback_search_radius_km)
            logger.info("Hub'Eau: no stations in bbox, expanding by %s km", fallback_search_radius_km)
            ids = _discover_stations_in_bbox(
                expanded, date_start=date_start, date_end=date_end,
                require_observations=require_observations,
            )
    else:
        raise ValueError("Either bbox or station_ids must be provided.")

    if not ids:
        logger.info("Hub'Eau: no stations found.")
        return []

    log_step("Hub'Eau: %d stations [%s -> %s]" % (len(ids), date_start.strftime("%Y-%m-%d"), date_end.strftime("%Y-%m-%d")))

    records: list[PointRecord] = []
    for sid in iter_progress(ids, desc="Stations"):
        location = _fetch_station_location(sid)
        obs_df = _download_observations(sid, product, date_start, date_end)
        if obs_df.empty:
            continue

        unit = "m3/s" if product in _DISCHARGE_VARS else "m"
        records.append(
            PointRecord(
                station_id=sid,
                variable="discharge" if product in _DISCHARGE_VARS else "water_level",
                source="hubeau",
                unit=unit,
                frequency="D",
                data=obs_df,
                date_start=date_start,
                date_end=date_end,
                location=location,
            )
        )

    log_step("Hub'Eau: %d station records loaded" % len(records))
    return records


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------
def _discover_stations_in_bbox(
    bbox: tuple,
    *,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    require_observations: bool = False,
) -> list[str]:
    """Query Hub'Eau referentiel to find station codes inside *bbox*.

    If require_observations is True, only returns stations that have
    data overlapping the requested period (based on station metadata dates).
    """
    xmin, ymin, xmax, ymax = bbox
    payload = get_json(
        f"{API_BASE}/referentiel/stations",
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
        sid = row.get("code_station")
        if not sid:
            continue

        if require_observations and date_start and date_end:
            # Check station active period overlap
            station_start = row.get("date_ouverture_station")
            station_end = row.get("date_fermeture_station")
            if not _station_period_overlaps(station_start, station_end, date_start, date_end):
                continue

        ids.append(str(sid))

    return ids


def _station_period_overlaps(
    station_start_str: str | None,
    station_end_str: str | None,
    req_start: datetime,
    req_end: datetime,
) -> bool:
    """Check if station active period overlaps with requested period."""
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


def _fetch_station_location(station_id: str) -> StationLocation | None:
    """Fetch one station's reference info and return a ``StationLocation``."""
    payload = get_json(
        f"{API_BASE}/referentiel/stations",
        params={"code_station": station_id, "size": 1, "format": "json"},
    )
    if payload is None:
        return None
    data = payload.get("data", [])
    if not data:
        return None

    info = data[0]
    lon = info.get("longitude_station")
    lat = info.get("latitude_station")
    if lon is None or lat is None:
        return None

    return StationLocation(
        id=station_id,
        x=float(lon),
        y=float(lat),
        crs="EPSG:4326",
        metadata={
            "station_name": info.get("libelle_station"),
            "x_l93": info.get("coordonnee_x_station"),
            "y_l93": info.get("coordonnee_y_station"),
            "city": info.get("libelle_commune"),
            "department": info.get("libelle_departement"),
            "altitude": info.get("altitude_ref_alti_station"),
            "start_date": info.get("date_ouverture_station"),
            "end_date": info.get("date_fermeture_station"),
        },
    )


# ---------------------------------------------------------------------------
# Observation download
# ---------------------------------------------------------------------------
def _download_observations(
    station_id: str,
    product: str,
    date_start: datetime,
    date_end: datetime,
) -> pd.DataFrame:
    """Download observations, chunked if period > MAX_DAYS_PER_CHUNK."""
    total_days = (date_end - date_start).days + 1
    if total_days <= MAX_DAYS_PER_CHUNK:
        return _get_obs_chunk(station_id, product, date_start, date_end)

    # Split into chunks
    chunks: list[pd.DataFrame] = []
    current = date_start
    while current <= date_end:
        chunk_end = min(current + timedelta(days=MAX_DAYS_PER_CHUNK - 1), date_end)
        chunk_df = _get_obs_chunk(station_id, product, current, chunk_end)
        if not chunk_df.empty:
            chunks.append(chunk_df)
        current = chunk_end + timedelta(days=1)
        if current <= date_end:
            time.sleep(0.5)

    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=["datetime", "value"])


def _get_obs_chunk(
    station_id: str,
    product: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Fetch one chunk of observations from ``obs_elab`` endpoint."""
    payload = get_json(
        f"{API_BASE}/obs_elab",
        params={
            "code_entite": station_id,
            "grandeur_hydro_elab": product,
            "date_debut_obs_elab": start.strftime("%Y-%m-%d"),
            "date_fin_obs_elab": end.strftime("%Y-%m-%d"),
            "size": 20_000,
            "format": "json",
        },
    )
    if payload is None:
        return pd.DataFrame(columns=["datetime", "value"])

    raw = payload.get("data", [])
    if not raw:
        return pd.DataFrame(columns=["datetime", "value"])

    df = pd.DataFrame(raw)

    # Normalize to standard columns
    out = pd.DataFrame()
    date_col = df["date_obs_elab"] if "date_obs_elab" in df.columns else pd.Series(dtype=object)
    value_col = df["resultat_obs_elab"] if "resultat_obs_elab" in df.columns else pd.Series(dtype=object)
    out["datetime"] = pd.to_datetime(date_col, errors="coerce")
    out["value"] = pd.to_numeric(value_col, errors="coerce")
    out["quality"] = df.get("libelle_qualification", "")

    # Convert Hub'Eau L/s → m³/s for discharge variables, mm → m for height
    if product in _DISCHARGE_VARS:
        out["value"] = out["value"] / 1000.0
    elif product in _HEIGHT_VARS:
        out["value"] = out["value"] / 1000.0

    out = out.dropna(subset=["datetime", "value"])
    return out.sort_values("datetime").reset_index(drop=True)
