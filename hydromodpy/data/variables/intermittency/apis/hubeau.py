"""Hub'Eau stream-flow (ecoulement) API adapter.

Produces ``PointRecord`` instances from the Hub'Eau v1 ecoulement endpoints
(ONDE - National Low-Flow Observatory).

Endpoints used:
- ``/v1/ecoulement/stations``     - station discovery (bbox, department, etc.)
- ``/v1/ecoulement/observations`` - flow-state observations per station

Flow state mapping (Hub'Eau code_ecoulement -> internal 1-5 ordinal):
    "1"  -> Visible flow              -> 5
    "1a" -> Acceptable visible flow   -> 4
    "1f" -> Weak visible flow         -> 3
    "2"  -> Non-visible flow          -> 2
    "3"  -> Dry (no water)            -> 1
    "4"  -> Observation impossible    -> dropped (NaN)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.console import progress
from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.api_client import get_json, paginate_json
from hydromodpy.data.common.clients.hubeau import station_location

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.data.contracts.location import StationLocation
    from hydromodpy.data.contracts.timeseries import PointRecord
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

logger = get_logger(__name__)

API_BASE = "https://hubeau.eaufrance.fr/api/v1/ecoulement"

COVERAGE = {
    "country": "FR",
    "description": "Hub'Eau stream-flow - ONDE stations metropolitan France",
    "variables": ["flow_state"],
    "frequency": ["irregular"],
}

# Hub'Eau code_ecoulement -> internal flow code (1 = dry ... 5 = fully flowing)
_CODE_ECOULEMENT_MAP: dict[str, int] = {
    "1": 5,  # Visible flow
    "1a": 4,  # Acceptable visible flow
    "1f": 3,  # Weak visible flow
    "2": 2,  # Non-visible flow
    "3": 1,  # Dry (no water)
    # "4" -> Observation impossible - intentionally omitted (NaN)
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def fetch(
    *,
    bbox: tuple | None = None,
    station_ids: Sequence[str] | None = None,
    code_departement: list[str] | None = None,
    date_start: datetime,
    date_end: datetime,
    require_observations: bool = True,
    fallback_search_radius_km: float | None = None,
) -> list[PointRecord]:
    """Fetch ONDE flow-state observations from Hub'Eau and return ``PointRecord`` list.

    Either *bbox*, *station_ids*, or *code_departement* must be provided.
    """
    # Resolve station list
    if station_ids:
        ids = [str(s).strip() for s in station_ids]
    elif bbox is not None or code_departement is not None:
        ids = _discover_stations(
            bbox=bbox,
            code_departement=code_departement,
            date_start=date_start,
            date_end=date_end,
            require_observations=require_observations,
        )
        if not ids and bbox is not None and fallback_search_radius_km:
            from hydromodpy.data.common.geo_helpers import expand_bbox

            expanded = expand_bbox(bbox, fallback_search_radius_km)
            logger.info(
                "Hub'Eau ONDE: no stations in bbox, expanding by %s km", fallback_search_radius_km
            )
            ids = _discover_stations(
                bbox=expanded,
                code_departement=code_departement,
                date_start=date_start,
                date_end=date_end,
                require_observations=require_observations,
            )
    else:
        raise ValueError("Either bbox, station_ids, or code_departement must be provided.")

    if not ids:
        logger.info("Hub'Eau ONDE: no stations found.")
        return []

    logger.debug(
        f"Hub'Eau ONDE: {len(ids)} stations "
        f"[{date_start.strftime('%Y-%m-%d')} -> {date_end.strftime('%Y-%m-%d')}]"
    )

    from hydromodpy.data.contracts.timeseries import PointRecord

    records: list[PointRecord] = []
    empty: list[str] = []
    for sid in progress.track(ids, "Fetching ONDE stations"):
        location = _fetch_station_location(sid)
        obs_df = _download_observations(sid, date_start, date_end)
        if obs_df.empty:
            empty.append(sid)
            continue

        records.append(
            PointRecord(
                station_id=sid,
                variable="flow_state",
                source="hubeau",
                unit="code",
                frequency="irregular",
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
                "intermittency",
                "hubeau",
                named=station_ids,
                dropped=empty,
                kept=records,
                reason=f"returned no observations between {date_start.strftime('%Y-%m-%d')} and {date_end.strftime('%Y-%m-%d')}",
                window=(date_start.strftime("%Y-%m-%d"), date_end.strftime("%Y-%m-%d")),
            )
        except ImportError:
            pass

    logger.debug(f"Hub'Eau ONDE: {len(records)} station records loaded")
    return records


class HubeauIntermittency:
    """The ONDE flow-state campaigns of Hub'Eau, behind the data-source port.

    ``code_departement`` narrows the discovery the request's extent drives;
    the download stays in :func:`fetch`, whose body this class does not
    restate.
    """

    source_id: ClassVar[str] = "hubeau"
    section: ClassVar[str] = "intermittency"
    payload_kind: ClassVar[PayloadKind] = "points"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent", "station_ids")
    period_need: ClassVar[PeriodNeed] = "required"
    writes_out_dir: ClassVar[bool] = False

    def __init__(
        self,
        *,
        code_departement: Sequence[str] | None = None,
        require_observations: bool = True,
        fallback_search_radius_km: float | None = None,
    ) -> None:
        self.code_departement = list(code_departement) if code_departement else None
        self.require_observations = require_observations
        self.fallback_search_radius_km = fallback_search_radius_km
        self.variables: tuple[str, ...] = ("flow_state",)
        self.hosts: tuple[str, ...] = shipped_hosts("hubeau")

    def fetch(self, request: FetchRequest) -> FetchResult:
        require_selectors(self, request)
        period = require_period(self, request)
        extent = extent_for(self, request) if request.extent is not None else None
        records = fetch(
            bbox=None if extent is None else extent.bbox,
            station_ids=list(request.station_ids) or None,
            date_start=period.start,
            date_end=period.end,
            code_departement=self.code_departement,
            require_observations=self.require_observations,
            fallback_search_radius_km=self.fallback_search_radius_km,
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


def _discover_stations(
    *,
    bbox: tuple | None = None,
    code_departement: list[str] | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    require_observations: bool = False,
) -> list[str]:
    """Query Hub'Eau ecoulement stations endpoint."""
    params: dict = {"size": 10_000, "format": "json"}
    if bbox is not None:
        xmin, ymin, xmax, ymax = bbox
        params["bbox"] = f"{xmin},{ymin},{xmax},{ymax}"
    if code_departement:
        params["code_departement"] = ",".join(code_departement)

    payload = get_json(None, f"{API_BASE}/stations", params=params)
    if payload is None:
        return []

    data = payload.get("data", [])
    ids: list[str] = []
    for row in data:
        sid = row.get("code_station")
        if not sid:
            continue
        # Filter by station activity if requested
        if require_observations and date_start and date_end:
            station_state = row.get("etat_station", "")
            if station_state and station_state.lower() == "gelée":  # "frozen" station
                continue
        ids.append(str(sid))

    return ids


def _fetch_station_location(station_id: str) -> StationLocation | None:
    """Fetch one station's reference info and return a ``StationLocation``."""

    payload = get_json(
        None,
        f"{API_BASE}/stations",
        params={"code_station": station_id, "size": 1, "format": "json"},
    )
    return station_location(
        station_id,
        payload,
        lon_key="longitude",
        lat_key="latitude",
        metadata=lambda info: {
            "station_name": info.get("libelle_station"),
            "stream_name": info.get("libelle_cours_eau"),
            "stream_code": info.get("code_cours_eau"),
            "city": info.get("libelle_commune"),
            "department": info.get("libelle_departement"),
            "department_code": info.get("code_departement"),
            "region": info.get("libelle_region"),
            "basin": info.get("libelle_bassin"),
        },
    )


# ---------------------------------------------------------------------------
# Observation download
# ---------------------------------------------------------------------------
def _download_observations(
    station_id: str,
    date_start: datetime,
    date_end: datetime,
) -> pd.DataFrame:
    """Download all ONDE observations for one station in the given period."""
    import pandas as pd

    params: dict = {
        "code_station": station_id,
        "date_observation_min": date_start.strftime("%Y-%m-%d"),
        "date_observation_max": date_end.strftime("%Y-%m-%d"),
        "size": 1000,
        "format": "json",
    }

    raw_records = paginate_json(
        None,
        f"{API_BASE}/observations",
        params=params,
        page_size=1000,
        data_key="data",
        count_key="count",
    )

    if not raw_records:
        return pd.DataFrame(columns=["datetime", "value"])

    rows: list[dict] = []
    for obs in raw_records:
        date_str = obs.get("date_observation")
        code_ecoulement = str(obs.get("code_ecoulement", "")).strip()
        flow_code = _CODE_ECOULEMENT_MAP.get(code_ecoulement)
        if flow_code is None:
            continue  # skip "Observation impossible" and unknown codes
        rows.append({"datetime": date_str, "value": flow_code})

    if not rows:
        return pd.DataFrame(columns=["datetime", "value"])

    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["datetime", "value"])
    return df.sort_values("datetime").reset_index(drop=True)
