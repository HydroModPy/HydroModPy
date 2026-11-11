"""Hub'Eau Piézométrie API adapter.

Produces ``PointRecord`` instances from the Hub'Eau v1 niveaux_nappes endpoints.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.console import progress
from hydromodpy.core.io.fetch import open_client
from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.api_client import get_json
from hydromodpy.data.common.clients.hubeau import keep_nearest, station_period_overlaps
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

logger = get_logger(__name__)

API_BASE = "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes"

COVERAGE = {
    "country": "FR",
    "description": "Hub'Eau Piézométrie - piézomètres France métropolitaine",
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
    client: HTTPClient,
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
    from hydromodpy.data.contracts.timeseries import PointRecord

    if station_ids:
        ids = list(station_ids)
    elif bbox is not None:
        ids = _discover_piezometers_in_bbox(
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
                "Hub'Eau piezo: no piezometers in bbox, expanding by %s km",
                fallback_search_radius_km,
            )
            ids = _discover_piezometers_in_bbox(
                expanded,
                date_start=date_start,
                date_end=date_end,
                require_observations=require_observations,
                client=client,
            )
    else:
        raise ValueError("Either bbox or station_ids must be provided.")

    # nearest_to: keep only the closest piezometer to the target point
    if nearest_to and ids:
        ids = keep_nearest(
            ids,
            nearest_to,
            lambda bss_id: _fetch_piezometer_location(bss_id, client=client),
            label="piezometry",
        )

    if not ids:
        logger.info("Hub'Eau piezo: no piezometers found.")
        return []

    logger.debug(
        f"Hub'Eau piezo: {len(ids)} piezometers "
        f"[{date_start.strftime('%Y-%m-%d')} -> {date_end.strftime('%Y-%m-%d')}]"
    )

    records: list[PointRecord] = []
    empty: list[str] = []
    for bss_id in progress.track(ids, "Fetching piezometers"):
        location = _fetch_piezometer_location(bss_id, client=client)
        obs_df = _download_chronicles(bss_id, product, date_start, date_end, client=client)
        if obs_df.empty:
            empty.append(bss_id)
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

    if empty:
        try:
            from hydromodpy.data.common.stations import report_dropped

            report_dropped(
                "piezometry",
                "hubeau",
                named=station_ids,
                dropped=empty,
                kept=records,
                reason=f"returned no {product} observation between {date_start.strftime('%Y-%m-%d')} and {date_end.strftime('%Y-%m-%d')}",
                product=product,
                window=(date_start.strftime("%Y-%m-%d"), date_end.strftime("%Y-%m-%d")),
            )
        except ImportError:
            pass

    logger.debug(f"Hub'Eau piezo: {len(records)} records loaded")
    return records


class HubeauPiezometry:
    """The BSS piezometers of Hub'Eau, behind the data-source port.

    ``nearest_to`` is what the variable resolves when the section asks for the
    nearest piezometer: the point it starts from depends on the project
    extent, which a source must not read by itself. The download stays in
    :func:`fetch`, whose body this class does not restate.
    """

    source_id: ClassVar[str] = "hubeau"
    section: ClassVar[str] = "piezometry"
    payload_kind: ClassVar[PayloadKind] = "points"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent", "station_ids")
    period_need: ClassVar[PeriodNeed] = "required"
    writes_out_dir: ClassVar[bool] = False

    def __init__(
        self,
        *,
        product: str = "level",
        require_observations: bool = True,
        fallback_search_radius_km: float | None = None,
        nearest_to: tuple[float, float] | None = None,
    ) -> None:
        self.product = product
        self.require_observations = require_observations
        self.fallback_search_radius_km = fallback_search_radius_km
        # Same fold as the record of fetch: a product that is not "level"
        # serves the depth, because that is what the download would return.
        self.variables: tuple[str, ...] = (
            ("groundwater_level",) if product == "level" else ("groundwater_depth",)
        )
        self.nearest_to = nearest_to
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
                nearest_to=self.nearest_to,
                require_observations=self.require_observations,
                fallback_search_radius_km=self.fallback_search_radius_km,
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


def _discover_piezometers_in_bbox(
    bbox: tuple,
    *,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    require_observations: bool = False,
    client: HTTPClient,
) -> list[str]:
    """Find piezometer BSS codes inside bbox.

    If require_observations is True, filters out piezometers whose
    measurement period does not overlap with the requested dates.
    """
    xmin, ymin, xmax, ymax = bbox
    payload = get_json(
        client,
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
            if not station_period_overlaps(station_start, station_end, date_start, date_end):
                continue

        ids.append(str(bss))

    return ids


def _fetch_piezometer_location(bss_id: str, *, client: HTTPClient) -> StationLocation | None:
    from hydromodpy.data.contracts.location import StationLocation

    payload = get_json(
        client,
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
    *,
    client: HTTPClient,
) -> pd.DataFrame:
    import pandas as pd

    from hydromodpy.data.common.files import parse_datetime_column

    all_records: list[dict] = []
    year = date_start.year
    while year <= date_end.year:
        y_start = max(date_start, datetime(year, 1, 1))
        y_end = min(date_end, datetime(year, 12, 31))
        payload = get_json(
            client,
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


__all__ = [
    "COVERAGE",
    "HubeauPiezometry",
    "fetch",
]
