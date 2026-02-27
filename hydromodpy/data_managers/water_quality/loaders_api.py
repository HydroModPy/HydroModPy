"""
API loader for water quality data.  The implementation mirrors
`piezometry/loaders_api.py` but must be adapted to the schema of the
qualite_rivieres and qualite_nappes endpoints.  The class below is a starting
point; you'll need to write the code that fetches parameter data and builds the
normalized ``ApiLoadResult``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd
import requests

try:
    from ..common.base_loaders import BaseApiLoader
    from .water_quality import WaterQuality
except ImportError:  # pragma: no cover
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _manager_dir = Path(__file__).resolve().parent
    for _path in (str(_manager_root), str(_manager_dir)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_loaders import BaseApiLoader
    from water_quality import WaterQuality


API_PZ_URL = "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/analyses"
API_RIVER_URL = "https://hubeau.eaufrance.fr/api/v2/qualite_rivieres/analyse_pc"

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
    stations_info: pd.DataFrame
    metadata: pd.DataFrame
    data: pd.DataFrame
    missing_data_summary: pd.DataFrame
    samples: Dict[str, WaterQuality]


class ApiWaterQualityLoader(BaseApiLoader):
    """Load water‑quality records from Hub'Eau web services."""

    STATUS_MESSAGES = STATUS_MESSAGES

    def __init__(
        self,
        *,
        site_type: str = "river",
        parameters: Optional[Sequence[str]] = None,
        display: bool = False,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ):
        self.site_type = str(site_type).strip().lower()
        self.parameters = list(parameters) if parameters is not None else None
        self.display = bool(display)
        self.date_start = date_start
        self.date_end = date_end

    def load(self, *, site_ids: Sequence[str]) -> ApiLoadResult:
        """Load and normalize data for multiple sites.  This is largely a copy of
        :meth:`ApiPiezometerLoader.load` with variable names changed; you will
        need to fill in the API-specific loops below."""
        print(f"Loading data for {len(site_ids)} water-quality sites...")

        all_stations_info = []
        all_metadata = []
        all_data = []
        all_missing_summary = []
        all_samples: Dict[str, WaterQuality] = {}

        for idx, site_id in enumerate(site_ids):
            site_id = str(site_id)
            print(f"\n[{idx + 1}/{len(site_ids)}] Processing site {site_id}")

            station_info = self._get_station_info(site_id)
            if station_info is None:
                print(f"WARNING: site {site_id} not found")
                continue

            station_info["site_id"] = site_id
            all_stations_info.append(station_info)

            metadata = self._build_metadata(site_id, station_info)
            all_metadata.append(metadata)

            data, missing_info = self._get_time_series(site_id, metadata)
            if not data.empty:
                data["site_id"] = site_id
                sample = WaterQuality(
                    site_id=site_id,
                    data=data,
                    metadata=metadata,
                )
                all_samples[site_id] = sample
                all_data.append(sample.data)

            if missing_info:
                missing_info["site_id"] = site_id
                all_missing_summary.append(missing_info)

        return ApiLoadResult(
            stations_info=pd.DataFrame(all_stations_info) if all_stations_info else pd.DataFrame(),
            metadata=pd.DataFrame(all_metadata) if all_metadata else pd.DataFrame(),
            data=pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame(),
            missing_data_summary=pd.DataFrame(all_missing_summary) if all_missing_summary else pd.DataFrame(),
            samples=all_samples,
        )

    def _get_station_info(self, site_id: str) -> Optional[dict]:
        # Try to locate a station/representation for the requested id using
        # the appropriate stations endpoint depending on `site_type`.
        site_id = str(site_id)
        if self.site_type.startswith("river"):
            url = API_RIVER_URL
            params = {"size": 20, "format": "json", "code_station": site_id}
        else:
            url = API_PZ_URL
            params = {"size": 20, "format": "json"}
            # prefer the short code when available
            if "/" in site_id:
                params["code_bss"] = site_id
            else:
                params["bss_id"] = site_id

        try:
            response = requests.get(url, params=params, timeout=30)
        except requests.exceptions.RequestException as exc:
            print(f"Warning: station lookup failed for {site_id}: {exc}")
            return None
        if not self._check_status_code(response.status_code):
            return None

        payload = response.json()
        if self.display:
            print(payload)
        rows = payload.get("data", [])
        # try to find a directly matching row
        for row in rows:
            for key in ("code_station", "code_bss", "bss_id", "id", "uri_station"):
                if key in row and str(row.get(key)) == site_id:
                    return row
        # fallback to first row when nothing matches
        return rows[0] if rows else None

    def _build_metadata(self, site_id: str, station_info: Mapping[str, object]) -> dict:
        # Extract common fields (best-effort) from station info returned by
        # the Hub'Eau endpoints.  The keys returned by the two endpoints vary
        # so we attempt several candidates.  Prioritize direct coordinate fields
        # (latitude/longitude) over geometry object.
        x_wgs84 = station_info.get("longitude") or station_info.get("longitude_station")
        y_wgs84 = station_info.get("latitude") or station_info.get("latitude_station")

        # Fallback to geometry object if direct fields not found
        if x_wgs84 is None or y_wgs84 is None:
            geometry = station_info.get("geometry")
            if isinstance(geometry, Mapping):
                coords = geometry.get("coordinates")
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    if x_wgs84 is None:
                        x_wgs84 = coords[0]
                    if y_wgs84 is None:
                        y_wgs84 = coords[1]

        metadata = {
            "site_id": site_id,
            "station_name": station_info.get("libelle_station")
            or station_info.get("nom_station")
            or station_info.get("code_bss")
            or site_id,
            "x_wgs84": x_wgs84,
            "y_wgs84": y_wgs84,
            "x_l93": station_info.get("x_l93"),
            "y_l93": station_info.get("y_l93"),
            "start_date": station_info.get("date_debut_mesure") or station_info.get("date_debut_prelevement") or station_info.get("date_debut"),
            "end_date": station_info.get("date_fin_mesure") or station_info.get("date_fin_prelevement") or station_info.get("date_fin"),
        }

        metadata["start_date"] = self._to_datetime_or_none(metadata["start_date"])
        metadata["end_date"] = self._to_datetime_or_none(metadata["end_date"])
        if metadata["end_date"] is None:
            metadata["end_date"] = datetime.now() - timedelta(days=1)

        return metadata

    def _get_time_series(
        self,
        site_id: str,
        metadata: Optional[dict] = None,
    ) -> Tuple[pd.DataFrame, dict]:
        if metadata is None:
            metadata = {}

        start_date = self.date_start if self.date_start else metadata.get("start_date")
        end_date = self.date_end if self.date_end else metadata.get("end_date")
        if not start_date or not end_date:
            print(f"Start/end date unavailable for {site_id}.")
            return pd.DataFrame(), {}

        print(f"Fetching data for site {site_id} from {start_date} to {end_date}...")
        all_records = []
        current_year = int(start_date.year)
        end_year = int(end_date.year)
        while current_year <= end_year:
            year_start = max(start_date, datetime(current_year, 1, 1))
            year_end = min(end_date, datetime(current_year + 1, 1, 1))
            params = {"size": 20000, "format": "json"}
            # filtering by station id
            if self.site_type.startswith("river"):
                params["code_station"] = site_id
                params["date_debut_prelevement"] = year_start.strftime("%Y-%m-%d")
                params["date_fin_prelevement"] = year_end.strftime("%Y-%m-%d")
                url = API_RIVER_URL
            else:
                # piezometer-style analyses endpoint uses bss_id/code_bss
                if "/" in site_id:
                    params["code_bss"] = site_id
                else:
                    params["bss_id"] = site_id
                params["date_debut_prelevement"] = year_start.strftime("%Y-%m-%d")
                params["date_fin_prelevement"] = year_end.strftime("%Y-%m-%d")
                url = API_PZ_URL

            try:
                response = requests.get(url, params=params, timeout=60)
            except requests.exceptions.RequestException as exc:
                print(f"Warning: analyses chunk fetch failed for {site_id} ({current_year}): {exc}")
                current_year += 1
                continue
            if not self._check_status_code(response.status_code):
                current_year += 1
                continue
            payload = response.json()
            if self.display:
                print(payload)
            all_records.extend(payload.get("data", []))
            current_year += 1

        if not all_records:
            return pd.DataFrame(), {}

        raw_df = pd.DataFrame(all_records)
        clean_df = WaterQuality.process_api_dataframe(
            raw_df,
            site_id=site_id,
            parameters=self.parameters,
        )
        
        # If station metadata didn't have coordinates, try to extract from the first record
        if (metadata.get("x_wgs84") is None or metadata.get("y_wgs84") is None) and not raw_df.empty:
            first_record = raw_df.iloc[0]
            if metadata.get("x_wgs84") is None and "longitude" in first_record.index:
                metadata["x_wgs84"] = first_record["longitude"]
            if metadata.get("y_wgs84") is None and "latitude" in first_record.index:
                metadata["y_wgs84"] = first_record["latitude"]
        
        missing_info = WaterQuality.compute_missing_data(
            clean_df,
            date_column="date_measure",
            start_date=start_date,
            end_date=end_date,
            id_field="site_id",
            id_value=site_id,
            verbose=True,
        )
        return clean_df, missing_info

    # you can also copy the date‑splitting loop from the piezometry loader
    # to handle large date ranges, and a _check_status_code helper as shown


# end of loaders_api.py
