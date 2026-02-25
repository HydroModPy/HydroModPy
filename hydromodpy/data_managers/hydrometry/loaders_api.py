"""Hydrometry API loader used by :class:`StationSet`.

This module isolates all Hub'Eau-specific loading logic:
- station/site lookup in reference endpoints,
- metadata normalization,
- chunked observations download,
- conversion to standardized :class:`~hydromodpy.data_managers.hydrometry.station.Station`
  instances.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd
import requests

try:
    from ..common.base_loaders import BaseApiLoader
    from .station import Station
except ImportError:
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _chronicles_dir = Path(__file__).resolve().parent
    for _path in (str(_manager_root), str(_chronicles_dir)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_loaders import BaseApiLoader
    from station import Station


API_BASE_URL = "https://hubeau.eaufrance.fr/api/v2/"

STATUS_MESSAGES = {
    200: "Success: All results present in the response",
    206: "Partial content: Some results may be missing",
    400: "Bad request: Check your request parameters",
    401: "Unauthorized: Check your credentials",
    403: "Forbidden: Check your permissions",
    404: "Not found: Check your URL",
    500: "Internal server error: Try again later",
}


@dataclass
class ApiLoadResult:
    """Normalized payload returned by :meth:`ApiStationLoader.load`.

    Attributes
    ----------
    stations_info
        Raw station reference table for loaded station identifiers.
    sites_info
        Raw site reference table associated with loaded stations.
    metadata
        One metadata row per loaded station with harmonized field names.
    data
        Concatenated observations table for all loaded stations.
    missing_data_summary
        Per-station completeness diagnostics over the analyzed period.
    stations
        Mapping ``station_id -> Station`` containing cleaned station series.
    """

    stations_info: pd.DataFrame
    sites_info: pd.DataFrame
    metadata: pd.DataFrame
    data: pd.DataFrame
    missing_data_summary: pd.DataFrame
    stations: Dict[str, Station]


class ApiStationLoader(BaseApiLoader):
    """Load hydrometric station series from Hub'Eau web services."""

    STATUS_MESSAGES = STATUS_MESSAGES

    def __init__(
        self,
        *,
        variable: str,
        display: bool = False,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ):
        """Configure a Hub'Eau loader instance.

        Parameters
        ----------
        variable
            Hub'Eau variable code (for example ``"QmnJ"``).
        display
            If ``True``, pretty-print raw JSON payloads for debugging.
        date_start, date_end
            Optional override period. If omitted, station metadata period is
            used when available.
        """
        self.variable = variable
        self.display = bool(display)
        self.date_start = date_start
        self.date_end = date_end

    def load(self, *, station_ids: Sequence[str], site_ids: Sequence[str]) -> ApiLoadResult:
        """Load and normalize station series for multiple stations.

        Parameters
        ----------
        station_ids
            Iterable of 10-char station identifiers.
        site_ids
            Iterable of 8-char site identifiers aligned with ``station_ids``.

        Returns
        -------
        ApiLoadResult
            Aggregated dataframes and instantiated :class:`Station` objects.
        """
        print(f"Loading data for {len(station_ids)} stations...")

        all_stations_info = []
        all_sites_info = []
        all_metadata = []
        all_data = []
        all_missing_summary = []
        all_stations: Dict[str, Station] = {}

        for idx, (station_id, site_id) in enumerate(zip(station_ids, site_ids)):
            station_id = str(station_id)
            site_id = str(site_id)
            print(f"\n[{idx + 1}/{len(station_ids)}] Processing station {station_id}")

            station_info = self._get_info(station_id, info_type="stations")
            site_info = self._get_info(site_id, info_type="sites")
            if station_info is None:
                print(f"WARNING: Station {station_id} not found")
                continue

            station_info["station_id"] = station_id
            all_stations_info.append(station_info)

            if site_info:
                site_info["site_id"] = site_id
                site_info["station_id"] = station_id
                all_sites_info.append(site_info)

            metadata = self._build_metadata(station_id, station_info, site_info)
            all_metadata.append(metadata)

            data, missing_info = self._get_discharge_data(station_id, metadata)
            if not data.empty:
                data["station_id"] = station_id
                station = Station(
                    station_id=station_id,
                    variable=self.variable,
                    data=data,
                    metadata=metadata,
                )
                all_stations[station_id] = station
                all_data.append(station.data)

            if missing_info:
                missing_info["station_id"] = station_id
                all_missing_summary.append(missing_info)

        return ApiLoadResult(
            stations_info=pd.DataFrame(all_stations_info) if all_stations_info else pd.DataFrame(),
            sites_info=pd.DataFrame(all_sites_info) if all_sites_info else pd.DataFrame(),
            metadata=pd.DataFrame(all_metadata) if all_metadata else pd.DataFrame(),
            data=pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame(),
            missing_data_summary=pd.DataFrame(all_missing_summary) if all_missing_summary else pd.DataFrame(),
            stations=all_stations,
        )

    def _get_info(self, id_val: str, info_type: str = "sites") -> Optional[dict]:
        """Return the reference entry for one station or site identifier.

        A direct filtered query is attempted first (``code_station`` or
        ``code_site``). If no strict match is found, the method falls back to
        paginated scanning.
        """
        query_key = "code_station" if info_type == "stations" else "code_site"
        direct_url = f"{API_BASE_URL}hydrometrie/referentiel/{info_type}"
        direct_params = {
            query_key: id_val,
            "size": 20,
            "format": "json",
        }

        try:
            response = requests.get(direct_url, params=direct_params, timeout=30)
            if self._check_status_code(response.status_code):
                direct_data = response.json().get("data", [])
                for info in direct_data:
                    if str(info.get(query_key)) == str(id_val):
                        return info
        except requests.exceptions.RequestException as exc:
            print(f"Warning: direct {info_type} lookup failed for {id_val}: {exc}")

        page = 1
        max_page = 1

        while page <= max_page:
            url = f"{API_BASE_URL}hydrometrie/referentiel/{info_type}?&page={page}&size=1000"
            try:
                response = requests.get(url, timeout=30)
            except requests.exceptions.RequestException as exc:
                print(f"Warning: paginated {info_type} lookup failed on page {page} for {id_val}: {exc}")
                return None
            if not self._check_status_code(response.status_code):
                return None

            payload = response.json()
            data_info = payload.get("data", [])
            if page == 1:
                max_page = ceil(payload.get("count", 0) / 1000)

            for info in data_info:
                if info_type == "stations" and info.get("code_station") == id_val:
                    return info
                if info_type == "sites" and info.get("code_site") == id_val:
                    return info
            page += 1

        return None

    def _build_metadata(
        self,
        station_id: str,
        station_info: Mapping[str, object],
        site_info: Optional[Mapping[str, object]] = None,
    ) -> dict:
        """Build a normalized station metadata dictionary.

        The output uses field names consumed by :class:`Station` and the
        higher-level export logic.
        """
        metadata = {
            "station_id": station_id,
            "site_id": station_id[:8],
            "name": station_info.get("libelle_site"),
            "station_name": station_info.get("libelle_station"),
            "x_l93": station_info.get("coordonnee_x_station"),
            "y_l93": station_info.get("coordonnee_y_station"),
            "x_wgs84": station_info.get("longitude_station"),
            "y_wgs84": station_info.get("latitude_station"),
            "city": station_info.get("libelle_commune"),
            "department": station_info.get("libelle_departement"),
            "region": station_info.get("libelle_region"),
            "start_date": station_info.get("date_ouverture_station"),
            "end_date": station_info.get("date_fermeture_station"),
            "altitude": station_info.get("altitude_ref_alti_station"),
        }

        if site_info:
            metadata.update(
                {
                    "watershed_area": site_info.get("surface_bv"),
                    "site_influence": site_info.get("influence_generale_site"),
                }
            )

        if pd.isna(metadata["end_date"]) or metadata["end_date"] is None:
            metadata["end_date"] = datetime.now() - timedelta(days=1)
        else:
            metadata["end_date"] = datetime.strptime(str(metadata["end_date"]), "%Y-%m-%dT%H:%M:%SZ")

        if metadata["start_date"]:
            metadata["start_date"] = datetime.strptime(str(metadata["start_date"]), "%Y-%m-%dT%H:%M:%SZ")

        return metadata

    def _get_discharge_data(
        self,
        station_id: str,
        metadata: Optional[dict] = None,
    ) -> Tuple[pd.DataFrame, dict]:
        """Download and process one station time series.

        Parameters
        ----------
        station_id
            Hub'Eau station code.
        metadata
            Optional pre-built metadata. When absent, it is fetched from
            reference endpoints.

        Returns
        -------
        tuple[pd.DataFrame, dict]
            Clean observations dataframe and completeness summary.
        """
        if metadata is None:
            metadata = {}

        if not metadata:
            station_info = self._get_info(station_id, info_type="stations")
            site_info = self._get_info(station_id[:8], info_type="sites")
            if station_info:
                metadata = self._build_metadata(station_id, station_info, site_info)

        start_date = self.date_start if self.date_start else metadata.get("start_date")
        end_date = self.date_end if self.date_end else metadata.get("end_date")
        if not start_date or not end_date:
            print(f"Start date and end date must be provided or available in metadata for {station_id}.")
            return pd.DataFrame(), {}

        print(f"Fetching data for station {station_id} from {start_date} to {end_date}...")
        total_days = (end_date - start_date).days + 1
        print(f"Total days to fetch: {total_days}")
        max_days_per_chunk = 20000

        if total_days <= max_days_per_chunk:
            print(f"  Simple request (<= {max_days_per_chunk} days)")
            result_df = self._get_data_chunk(station_id, start_date, end_date, metadata=metadata)
        else:
            num_chunks = (total_days + max_days_per_chunk - 1) // max_days_per_chunk
            print(f"  Splitting into {num_chunks} chunks of {max_days_per_chunk} days max")
            result_df = pd.DataFrame()
            current_date = start_date

            for chunk_num in range(num_chunks):
                chunk_start = current_date
                chunk_end = min(current_date + timedelta(days=max_days_per_chunk - 1), end_date)
                print(
                    f"  Chunk {chunk_num + 1}/{num_chunks}: "
                    f"{chunk_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}"
                )
                chunk_df = self._get_data_chunk(station_id, chunk_start, chunk_end, metadata=metadata)
                if not chunk_df.empty:
                    result_df = pd.concat([result_df, chunk_df], ignore_index=True)

                current_date = chunk_end + timedelta(days=1)
                if current_date > end_date:
                    break
                time.sleep(1)

        missing_info = Station.compute_missing_data(
            result_df,
            start_date=start_date,
            end_date=end_date,
            station_id=station_id,
            verbose=True,
        )
        return result_df, missing_info

    def _get_data_chunk(
        self,
        station_id: str,
        start_date: datetime,
        end_date: datetime,
        *,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> pd.DataFrame:
        """Request one date chunk from ``obs_elab`` and normalize results.

        Returns an empty dataframe when no observations are available or when
        the HTTP/JSON layer fails for the requested chunk.
        """
        date_start_str = start_date.strftime("%Y-%m-%d")
        date_end_str = end_date.strftime("%Y-%m-%d")
        url = (
            f"{API_BASE_URL}hydrometrie/obs_elab?code_entite={station_id}"
            f"&grandeur_hydro_elab={self.variable}&size=20000"
            f"&date_debut_obs_elab={date_start_str}&date_fin_obs_elab={date_end_str}"
        )

        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            payload = response.json()

            if self.display:
                print(json.dumps(payload, indent=1))

            total_count = payload.get("count", 0)
            raw_df = pd.DataFrame(payload.get("data", []))
            if raw_df.empty:
                print("    No data found for this period")
                return pd.DataFrame()

            print(f"    {len(raw_df)} records retrieved out of {total_count} available")
            if len(raw_df) < total_count:
                print(f"    Warning: only {len(raw_df)}/{total_count} records retrieved (API limit reached)")

            watershed_area = None
            if metadata:
                watershed_area = metadata.get("watershed_area")

            return Station.process_api_dataframe(
                raw_df,
                variable=self.variable,
                station_id=station_id,
                watershed_area=watershed_area,
            )
        except requests.exceptions.RequestException as exc:
            print(f"    Request error for {station_id}: {exc}")
            return pd.DataFrame()
        except ValueError as exc:
            print(f"    JSON parsing error for {station_id}: {exc}")
            return pd.DataFrame()

