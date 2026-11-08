"""Hub'Eau Hydrométrie API adapter.

Produces ``PointRecord`` instances from the Hub'Eau v2 hydrometrie endpoints.
This adapter is self-contained: it manages its own HTTP calls via the
shared ``api_client`` module and converts raw JSON to the standard contract.
:class:`HubeauHydrometry` holds the port-facing side of the same download.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.console import progress
from hydromodpy.core.console.progress import MILESTONE
from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.api_client import get_json
from hydromodpy.data.common.clients.hubeau import station_location, station_period_overlaps
from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
    require_declared_variables,
    require_period,
    require_selectors,
    shipped_hosts,
)

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.data.contracts.location import StationLocation
    from hydromodpy.data.contracts.timeseries import PointRecord

logger = get_logger(__name__)

API_BASE = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"

COVERAGE = {
    "country": "FR",
    "description": "Hub'Eau Hydrométrie - stations France métropolitaine",
    "variables": ["QmnJ", "QmM", "QINM", "QINnJ", "QixM", "QIXnJ", "HIXM", "HIXnJ"],
    "frequency": ["D", "ME"],
}

# Hub'Eau discharge variables reported in L/s that we convert to m³/s
_DISCHARGE_VARS = {"QmnJ", "QmM", "QINM", "QINnJ", "QixM", "QIXnJ"}
_HEIGHT_VARS = {"HIXM", "HIXnJ"}
MAX_DAYS_PER_CHUNK = 20_000
_STATION_INFLUENCE_FIELDS = (
    "influence_generale_site",
    "commentaire_influence_generale_site",
    "influence_locale_station",
    "commentaire_influence_locale_station",
    "commentaire_station",
)


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
    max_stations: int | None = None,
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
            bbox,
            date_start=date_start,
            date_end=date_end,
            require_observations=require_observations,
        )
        if not ids and fallback_search_radius_km:
            from hydromodpy.data.common.geo_helpers import expand_bbox

            expanded = expand_bbox(bbox, fallback_search_radius_km)
            logger.info(
                "Hub'Eau: no stations in bbox, expanding by %s km", fallback_search_radius_km
            )
            ids = _discover_stations_in_bbox(
                expanded,
                date_start=date_start,
                date_end=date_end,
                require_observations=require_observations,
            )
    else:
        raise ValueError("Either bbox or station_ids must be provided.")

    if not ids:
        logger.info("Hub'Eau: no stations found.")
        return []

    logger.debug(
        f"Hub'Eau: {len(ids)} stations "
        f"[{date_start.strftime('%Y-%m-%d')} -> {date_end.strftime('%Y-%m-%d')}]"
    )

    from hydromodpy.data.contracts.timeseries import PointRecord

    records: list[PointRecord] = []
    empty: list[str] = []
    for sid in progress.track(ids, "Fetching hydrometry stations"):
        # max_stations caps the stations KEPT, not the ids tried: capping the ids
        # first let stations with no data in the period consume the quota and
        # crowd out the ones that have some.
        if max_stations is not None and len(records) >= max_stations:
            break
        location = _fetch_station_location(sid)
        obs_df = _download_observations(sid, product, date_start, date_end)
        if obs_df.empty:
            empty.append(sid)
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

    if empty:
        logger.warning(
            "Hub'Eau: %d of %d stations returned no %s observation between %s and %s and were "
            "dropped: %s. Their declared service period overlaps the window, which is all "
            "require_observations can check before downloading.",
            len(empty),
            len(ids),
            product,
            date_start.strftime("%Y-%m-%d"),
            date_end.strftime("%Y-%m-%d"),
            ", ".join(empty[:10]) + (" ..." if len(empty) > 10 else ""),
        )
    # Same reason as the BD Topage fetch: what a run downloaded from Hub'Eau is
    # part of where its numbers come from, so it survives the default verbosity.
    logger.info("Hub'Eau: %d station records loaded", len(records), extra=MILESTONE)
    return records


class HubeauHydrometry:
    """The discharge and stage stations of Hub'Eau, behind the data-source port.

    The class holds what one ``[[data.hydrometry.sources]]`` entry names
    (``product``, ``require_observations``, and the discovery fallbacks); the
    request holds what varies between two calls. The download itself stays in
    :func:`fetch`, whose body this class does not restate.
    """

    source_id: ClassVar[str] = "hubeau"
    section: ClassVar[str] = "hydrometry"
    payload_kind: ClassVar[PayloadKind] = "points"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent", "station_ids")
    period_need: ClassVar[PeriodNeed] = "required"
    writes_out_dir: ClassVar[bool] = False

    def __init__(
        self,
        *,
        product: str = "QmnJ",
        require_observations: bool = True,
        fallback_search_radius_km: float | None = None,
        max_stations: int | None = None,
    ) -> None:
        self.product = product
        self.require_observations = require_observations
        self.fallback_search_radius_km = fallback_search_radius_km
        self.max_stations = max_stations
        # Same fold as the unit of a record in fetch: an unknown product
        # serves a height, because that is what the download would return.
        self.variables: tuple[str, ...] = (
            ("discharge",) if product in _DISCHARGE_VARS else ("water_level",)
        )
        self.hosts: tuple[str, ...] = shipped_hosts("hubeau")

    def fetch(self, request: FetchRequest) -> FetchResult:
        require_selectors(self, request)
        period = require_period(self, request)
        extent = extent_for(self, request) if request.extent is not None else None
        records = fetch(
            product=self.product,
            bbox=None if extent is None else extent.bbox,
            station_ids=list(request.station_ids) or None,
            date_start=period.start,
            date_end=period.end,
            require_observations=self.require_observations,
            fallback_search_radius_km=self.fallback_search_radius_km,
            max_stations=self.max_stations,
        )
        require_declared_variables(self, [record.variable for record in records])
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=period,
            points=tuple(records),
        )


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------


def discover_stations(
    bbox: tuple,
    *,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    require_observations: bool = False,
) -> list[dict]:
    """Return the Hub'Eau reference rows of the stations inside a WGS84 *bbox*.

    Each row is the raw ``referentiel/stations`` record: ``code_station``,
    ``code_site``, ``libelle_station``, ``longitude_station``,
    ``latitude_station``, ``date_ouverture_station``, ``date_fermeture_station``
    and the rest. With ``require_observations`` only the stations whose service
    period overlaps the requested one are kept.
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
    rows: list[dict] = []
    for row in payload.get("data", []):
        if not row.get("code_station"):
            continue
        if require_observations and date_start and date_end:
            station_start = row.get("date_ouverture_station")
            station_end = row.get("date_fermeture_station")
            if not station_period_overlaps(station_start, station_end, date_start, date_end):
                continue
        rows.append(row)
    return rows


def _discover_stations_in_bbox(
    bbox: tuple,
    *,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    require_observations: bool = False,
) -> list[str]:
    """Return the codes of the stations inside *bbox* (see :func:`discover_stations`)."""
    rows = discover_stations(
        bbox,
        date_start=date_start,
        date_end=date_end,
        require_observations=require_observations,
    )
    return [str(row["code_station"]) for row in rows]


def _fetch_station_location(station_id: str) -> StationLocation | None:
    """Fetch one station's reference info and return a ``StationLocation``."""
    payload = get_json(
        f"{API_BASE}/referentiel/stations",
        params={"code_station": station_id, "size": 1, "format": "json"},
    )
    return station_location(
        station_id,
        payload,
        lon_key="longitude_station",
        lat_key="latitude_station",
        metadata=_station_metadata,
    )


def _station_metadata(info: dict) -> dict:
    metadata = {
        "station_name": info.get("libelle_station"),
        "x_l93": info.get("coordonnee_x_station"),
        "y_l93": info.get("coordonnee_y_station"),
        "city": info.get("libelle_commune"),
        "department": info.get("libelle_departement"),
        "altitude": info.get("altitude_ref_alti_station"),
        "start_date": info.get("date_ouverture_station"),
        "end_date": info.get("date_fermeture_station"),
    }
    metadata.update(
        {key: info.get(key) for key in _STATION_INFLUENCE_FIELDS if info.get(key) not in (None, "")}
    )
    return metadata


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
    import pandas as pd

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

    return (
        pd.concat(chunks, ignore_index=True)
        if chunks
        else pd.DataFrame(columns=["datetime", "value"])
    )


def _get_obs_chunk(
    station_id: str,
    product: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Fetch one chunk of observations from ``obs_elab`` endpoint."""
    import pandas as pd

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
    value_col = (
        df["resultat_obs_elab"] if "resultat_obs_elab" in df.columns else pd.Series(dtype=object)
    )
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
