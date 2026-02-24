"""Piezometry API loader used by :class:`PiezometerSet`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd
import requests

try:
    from ..common.base_loaders import BaseApiLoader
    from .piezometer import Piezometer
except ImportError:
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _manager_dir = Path(__file__).resolve().parent
    for _path in (str(_manager_root), str(_manager_dir)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_loaders import BaseApiLoader
    from piezometer import Piezometer


API_BASE_URL = "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/"

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
    """Normalized payload returned by :meth:`ApiPiezometerLoader.load`."""

    stations_info: pd.DataFrame
    metadata: pd.DataFrame
    data: pd.DataFrame
    missing_data_summary: pd.DataFrame
    piezometers: Dict[str, Piezometer]


class ApiPiezometerLoader(BaseApiLoader):
    """Load piezometric station series from Hub'Eau web services."""

    STATUS_MESSAGES = STATUS_MESSAGES

    def __init__(
        self,
        *,
        measurement: str,
        display: bool = False,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ):
        self.measurement = measurement
        self.display = bool(display)
        self.date_start = date_start
        self.date_end = date_end

    def load(self, *, piezometer_ids: Sequence[str]) -> ApiLoadResult:
        """Load and normalize station series for multiple piezometers."""
        print(f"Loading data for {len(piezometer_ids)} piezometers...")

        all_stations_info = []
        all_metadata = []
        all_data = []
        all_missing_summary = []
        all_piezometers: Dict[str, Piezometer] = {}

        for idx, piezometer_id in enumerate(piezometer_ids):
            piezometer_id = str(piezometer_id)
            print(f"\n[{idx + 1}/{len(piezometer_ids)}] Processing piezometer {piezometer_id}")

            station_info = self._get_station_info(piezometer_id)
            if station_info is None:
                print(f"WARNING: Piezometer {piezometer_id} not found")
                continue

            station_info["piezometer_id"] = piezometer_id
            all_stations_info.append(station_info)

            metadata = self._build_metadata(piezometer_id, station_info)
            all_metadata.append(metadata)

            data, missing_info = self._get_chronicle_data(piezometer_id, metadata)
            if not data.empty:
                data["piezometer_id"] = piezometer_id
                piezometer = Piezometer(
                    piezometer_id=piezometer_id,
                    measurement=self.measurement,
                    data=data,
                    metadata=metadata,
                )
                all_piezometers[piezometer_id] = piezometer
                all_data.append(piezometer.data)

            if missing_info:
                missing_info["piezometer_id"] = piezometer_id
                all_missing_summary.append(missing_info)

        return ApiLoadResult(
            stations_info=pd.DataFrame(all_stations_info) if all_stations_info else pd.DataFrame(),
            metadata=pd.DataFrame(all_metadata) if all_metadata else pd.DataFrame(),
            data=pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame(),
            missing_data_summary=pd.DataFrame(all_missing_summary) if all_missing_summary else pd.DataFrame(),
            piezometers=all_piezometers,
        )

    def _get_station_info(self, piezometer_id: str) -> Optional[dict]:
        """Return reference entry for one piezometer identifier."""
        url = f"{API_BASE_URL}stations"
        params = {
            "code_bss": piezometer_id,
            "size": 20,
            "format": "json",
        }
        try:
            response = requests.get(url, params=params, timeout=30)
        except requests.exceptions.RequestException as exc:
            print(f"Warning: station lookup failed for {piezometer_id}: {exc}")
            return None
        if not self._check_status_code(response.status_code):
            return None

        payload = response.json()
        if self.display:
            print(payload)
        rows = payload.get("data", [])
        for row in rows:
            if str(row.get("code_bss")) == str(piezometer_id):
                return row
        return rows[0] if rows else None

    def _build_metadata(
        self,
        piezometer_id: str,
        station_info: Mapping[str, object],
    ) -> dict:
        """Build a normalized piezometer metadata dictionary."""
        x_wgs84 = None
        y_wgs84 = None
        geometry = station_info.get("geometry")
        if isinstance(geometry, Mapping):
            coordinates = geometry.get("coordinates")
            if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
                x_wgs84 = coordinates[0]
                y_wgs84 = coordinates[1]

        metadata = {
            "piezometer_id": piezometer_id,
            "station_name": station_info.get("libelle_station", station_info.get("code_bss", piezometer_id)),
            "x_wgs84": station_info.get("longitude_station", x_wgs84),
            "y_wgs84": station_info.get("latitude_station", y_wgs84),
            "x_l93": station_info.get("x_l93"),
            "y_l93": station_info.get("y_l93"),
            "investigation_depth_m": station_info.get("profondeur_investigation"),
            "station_altitude_m": station_info.get("altitude_station"),
            "start_date": station_info.get("date_debut_mesure"),
            "end_date": station_info.get("date_fin_mesure"),
        }

        metadata["start_date"] = self._to_datetime_or_none(metadata["start_date"])
        metadata["end_date"] = self._to_datetime_or_none(metadata["end_date"])
        if metadata["end_date"] is None:
            metadata["end_date"] = datetime.now() - timedelta(days=1)

        return metadata

    def _get_chronicle_data(
        self,
        piezometer_id: str,
        metadata: Optional[dict] = None,
    ) -> Tuple[pd.DataFrame, dict]:
        """Download and process one piezometer time series."""
        if metadata is None:
            metadata = {}

        start_date = self.date_start if self.date_start else metadata.get("start_date")
        end_date = self.date_end if self.date_end else metadata.get("end_date")
        if not start_date or not end_date:
            print(f"Start/end date unavailable for {piezometer_id}.")
            return pd.DataFrame(), {}

        print(f"Fetching data for piezometer {piezometer_id} from {start_date} to {end_date}...")
        all_records = []
        current_year = int(start_date.year)
        end_year = int(end_date.year)
        while current_year <= end_year:
            year_start = max(start_date, datetime(current_year, 1, 1))
            year_end = min(end_date, datetime(current_year + 1, 1, 1))
            params = {
                "code_bss": piezometer_id,
                "date_debut_mesure": year_start.strftime("%Y-%m-%d"),
                "date_fin_mesure": year_end.strftime("%Y-%m-%d"),
                "size": 20000,
                "format": "json",
            }
            try:
                response = requests.get(f"{API_BASE_URL}chroniques", params=params, timeout=60)
            except requests.exceptions.RequestException as exc:
                print(f"Warning: chronicle chunk fetch failed for {piezometer_id} ({current_year}): {exc}")
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
        clean_df = Piezometer.process_api_dataframe(
            raw_df,
            measurement=self.measurement,
            piezometer_id=piezometer_id,
        )
        missing_info = Piezometer.compute_missing_data(
            clean_df,
            start_date=start_date,
            end_date=end_date,
            piezometer_id=piezometer_id,
            verbose=True,
        )
        return clean_df, missing_info

