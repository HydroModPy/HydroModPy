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
from hydromodpy.core.io.fetch import open_client
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.bounds import Bounds
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

    from hydromodpy.core.io.fetch import HTTPClient
    from hydromodpy.data.contracts.location import StationLocation
    from hydromodpy.data.contracts.timeseries import PointRecord

from dataclasses import dataclass

logger = get_logger(__name__)

API_BASE = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"


@dataclass(frozen=True, slots=True)
class HubeauProduct:
    """Specification of one Hub'Eau hydrometry product.

    ``divisor`` is what a served value is divided by to reach ``unit``:
    1000 for the l/s to m3/s and the mm to m products. A division by 1000,
    not a multiplication by 1e-3, so the seven other products keep the exact
    float the old ````/ 1000.0```` wrote.
    """

    variable: str
    served_unit: str
    unit: str
    divisor: int
    frequency: str


PRODUCTS: dict[str, HubeauProduct] = {
    "QmnJ": HubeauProduct("discharge", "l/s", "m3/s", 1000, "D"),
    "QmM": HubeauProduct("discharge", "l/s", "m3/s", 1000, "ME"),
    "QINnJ": HubeauProduct("discharge", "l/s", "m3/s", 1000, "D"),
    "QINM": HubeauProduct("discharge", "l/s", "m3/s", 1000, "ME"),
    "QIXnJ": HubeauProduct("discharge", "l/s", "m3/s", 1000, "D"),
    "QIXM": HubeauProduct("discharge", "l/s", "m3/s", 1000, "ME"),
    "HIXnJ": HubeauProduct("water_level", "mm", "m", 1000, "D"),
    "HIXM": HubeauProduct("water_level", "mm", "m", 1000, "ME"),
}

COVERAGE = {
    "country": "FR",
    "description": "Hub'Eau Hydrométrie - stations France métropolitaine",
    "variables": list(PRODUCTS.keys()),
    "frequency": ["D", "ME"],
}

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
    raise_on_empty: bool = False,
    client: HTTPClient | None = None,
) -> list[PointRecord]:
    """Fetch hydrometry data from Hub'Eau and return ``PointRecord`` list.

    Either *bbox* or *station_ids* (or both) must be provided.
    If require_observations is True (default), stations without data
    in the period are filtered out during discovery.
    If no stations are found and fallback_search_radius_km is set,
    the bbox is expanded and discovery retried.
    """
    if client is None:
        with open_client(Bounds()) as opened:
            return fetch(
                product=product,
                bbox=bbox,
                station_ids=station_ids,
                date_start=date_start,
                date_end=date_end,
                require_observations=require_observations,
                fallback_search_radius_km=fallback_search_radius_km,
                max_stations=max_stations,
                raise_on_empty=raise_on_empty,
                client=opened,
            )
    # Resolve station list
    if station_ids:
        ids = [_normalize_station_id(s) for s in station_ids]
    elif bbox is not None:
        ids = _discover_stations_in_bbox(
            bbox,
            date_start=date_start,
            date_end=date_end,
            require_observations=require_observations,
            client=client,
        )
        if not ids and fallback_search_radius_km:
            from hydromodpy.data.common.geometry import expand_bbox

            expanded = expand_bbox(bbox, fallback_search_radius_km)
            logger.info(
                "Hub'Eau: no stations in bbox, expanding by %s km", fallback_search_radius_km
            )
            ids = _discover_stations_in_bbox(
                expanded,
                date_start=date_start,
                date_end=date_end,
                require_observations=require_observations,
                client=client,
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

    prod = PRODUCTS[product]
    var_name = prod.variable
    unit = prod.unit
    freq = prod.frequency

    records: list[PointRecord] = []
    empty: list[str] = []
    is_named = bool(station_ids)
    for sid in progress.track(ids, "Fetching hydrometry stations"):
        # max_stations caps only stations found by search, never named stations
        if not is_named and max_stations is not None and len(records) >= max_stations:
            break
        location = _fetch_station_location(sid, client=client)
        obs_df = _download_observations(sid, product, date_start, date_end, client=client)
        if obs_df.empty:
            empty.append(sid)
            continue

        records.append(
            PointRecord(
                station_id=sid,
                variable=var_name,
                source="hubeau",
                unit=unit,
                frequency=freq,
                data=obs_df,
                date_start=date_start,
                date_end=date_end,
                location=location,
            )
        )

    if empty:
        from hydromodpy.data.common.stations import report_dropped

        report_dropped(
            "hydrometry",
            "hubeau",
            named=station_ids,
            dropped=empty,
            kept=records,
            reason=f"returned no {product} observation between {date_start.strftime('%Y-%m-%d')} and {date_end.strftime('%Y-%m-%d')}",
            product=product,
            window=(date_start.strftime("%Y-%m-%d"), date_end.strftime("%Y-%m-%d")),
            raise_on_empty=raise_on_empty,
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
        self.variables: tuple[str, ...] = (PRODUCTS[product].variable,)
        self.hosts: tuple[str, ...] = shipped_hosts("hubeau")

    def fetch(self, request: FetchRequest) -> FetchResult:
        require_selectors(self, request)
        period = require_period(self, request)
        extent = extent_for(self, request) if request.extent is not None else None
        with open_client(request.bounds) as client:
            records = fetch(
                product=self.product,
                bbox=None if extent is None else extent.bbox,
                station_ids=list(request.station_ids) or None,
                date_start=period.start,
                date_end=period.end,
                require_observations=self.require_observations,
                fallback_search_radius_km=self.fallback_search_radius_km,
                max_stations=self.max_stations,
                raise_on_empty=True,
                client=client,
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
    client: HTTPClient | None = None,
) -> list[dict]:
    """Return the Hub'Eau reference rows of the stations inside a WGS84 *bbox*.

    Each row is the raw ``referentiel/stations`` record: ``code_station``,
    ``code_site``, ``libelle_station``, ``longitude_station``,
    ``latitude_station``, ``date_ouverture_station``, ``date_fermeture_station``
    and the rest. With ``require_observations`` only the stations whose service
    period overlaps the requested one are kept.
    """
    if client is None:
        with open_client(Bounds()) as opened:
            return discover_stations(
                bbox,
                date_start=date_start,
                date_end=date_end,
                require_observations=require_observations,
                client=opened,
            )
    xmin, ymin, xmax, ymax = bbox
    payload = get_json(
        client,
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
    client: HTTPClient | None = None,
) -> list[str]:
    """Return the codes of the stations inside *bbox* (see :func:`discover_stations`)."""
    rows = discover_stations(
        bbox,
        date_start=date_start,
        date_end=date_end,
        require_observations=require_observations,
        client=client,
    )
    return [str(row["code_station"]) for row in rows]


def _fetch_station_location(
    station_id: str, *, client: HTTPClient | None = None
) -> StationLocation | None:
    """Fetch one station's reference info and return a ``StationLocation``."""
    if client is None:
        with open_client(Bounds()) as opened:
            return _fetch_station_location(station_id, client=opened)
    payload = get_json(
        client,
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
    *,
    client: HTTPClient | None = None,
) -> pd.DataFrame:
    """Download observations, chunked if period > MAX_DAYS_PER_CHUNK."""
    import pandas as pd

    if client is None:
        with open_client(Bounds()) as opened:
            return _download_observations(station_id, product, date_start, date_end, client=opened)

    total_days = (date_end - date_start).days + 1
    if total_days <= MAX_DAYS_PER_CHUNK:
        return _get_obs_chunk(station_id, product, date_start, date_end, client=client)

    # Split into chunks
    chunks: list[pd.DataFrame] = []
    current = date_start
    while current <= date_end:
        chunk_end = min(current + timedelta(days=MAX_DAYS_PER_CHUNK - 1), date_end)
        chunk_df = _get_obs_chunk(station_id, product, current, chunk_end, client=client)
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
    *,
    client: HTTPClient | None = None,
) -> pd.DataFrame:
    """Fetch one chunk of observations from ``obs_elab`` endpoint."""
    import pandas as pd

    payload = get_json(
        client,
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

    # Convert the served unit to the record one: l/s -> m3/s, mm -> m. A
    # division by the table divisor, never a multiplication by a float
    # factor, so the seven products that already divided keep their bits.
    out["value"] = out["value"] / PRODUCTS[product].divisor

    out = out.dropna(subset=["datetime", "value"])
    return out.sort_values("datetime").reset_index(drop=True)
