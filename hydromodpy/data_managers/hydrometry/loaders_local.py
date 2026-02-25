"""Local hydrometry loader for previously exported station files.

The loader expects station CSV files plus optional reference tables produced by
the ``StationSet`` full export mode (metadata, stations_info, sites_info).
It normalizes rows into :class:`~hydromodpy.data_managers.hydrometry.station.Station`
instances and computes completeness diagnostics consistently with API mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd

try:
    from ..common.base_loaders import BaseLocalLoader
    from .station import Station
except ImportError:
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _chronicles_dir = Path(__file__).resolve().parent
    for _path in (str(_manager_root), str(_chronicles_dir)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_loaders import BaseLocalLoader
    from station import Station


@dataclass
class LocalLoadResult:
    """Normalized payload returned by :meth:`LocalStationLoader.load`.

    Attributes
    ----------
    stations_info
        Station reference rows corresponding to loaded station ids.
    sites_info
        Site reference rows corresponding to loaded station ids.
    metadata
        Metadata rows filtered to loaded stations.
    data
        Concatenated local station records with a ``station_id`` column.
    missing_data_summary
        Per-station completeness summary dataframe.
    stations
        Mapping ``station_id -> Station`` for loaded stations.
    """

    stations_info: pd.DataFrame
    sites_info: pd.DataFrame
    metadata: pd.DataFrame
    data: pd.DataFrame
    missing_data_summary: pd.DataFrame
    stations: Dict[str, Station]


class LocalStationLoader(BaseLocalLoader):
    """Load station series from local CSV exports."""

    def __init__(
        self,
        *,
        variable: str,
        local_data_dir: Path,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ):
        """Configure a local station loader.

        Parameters
        ----------
        variable
            Hydrometric variable code used to tag built stations.
        local_data_dir
            Directory containing station files (``<station_id>_*.csv`` or
            ``<station_id>.csv``) and optional reference tables.
        date_start, date_end
            Optional date filtering bounds applied after reading each station
            file.
        """
        self.variable = variable
        self.local_data_dir = Path(local_data_dir)
        self.date_start = date_start
        self.date_end = date_end

    def load(self, *, station_ids: Sequence[str]) -> LocalLoadResult:
        """Load selected stations from local exported files."""
        print(f"Loading LOCAL data for {len(station_ids)} stations from: {self.local_data_dir}")

        metadata_df, stations_info_df, sites_info_df, _ = self._load_reference_tables()
        all_data = []
        all_missing_summary = []
        all_stations: Dict[str, Station] = {}

        for idx, station_id in enumerate(station_ids):
            station_id = str(station_id)
            print(f"\n[{idx + 1}/{len(station_ids)}] Loading local station {station_id}")
            station_file = self._find_station_file(station_id)
            if station_file is None:
                print(f"WARNING: local file not found for station {station_id}")
                continue

            try:
                station_data = pd.read_csv(station_file)
            except Exception as exc:
                print(f"WARNING: failed to read {station_file}: {exc}")
                continue

            if station_data.empty:
                print(f"WARNING: no rows in {station_file}")
                continue

            station_data["station_id"] = station_id
            station_data = Station.filter_by_date_range(
                station_data,
                date_start=self.date_start,
                date_end=self.date_end,
            )
            if station_data.empty:
                print(f"  No rows remaining after date filtering for {station_id}")
                continue

            station_metadata = self._extract_station_metadata(station_id, metadata_df)
            station_metadata = self._enrich_station_metadata_with_coordinates(
                station_id=station_id,
                station_metadata=station_metadata,
                stations_info=stations_info_df,
            )

            station = Station(
                station_id=station_id,
                variable=self.variable,
                data=station_data,
                metadata=station_metadata,
            )
            all_stations[station_id] = station
            all_data.append(station.data)

            analysis_start, analysis_end = self._resolve_analysis_date_range(
                station_id=station_id,
                station_data=station.data,
                metadata_df=metadata_df,
            )
            if analysis_start is not None and analysis_end is not None:
                all_missing_summary.append(
                    station.completeness(
                        start_date=analysis_start,
                        end_date=analysis_end,
                    )
                )

        data_df = pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()
        missing_df = pd.DataFrame(all_missing_summary) if all_missing_summary else pd.DataFrame()

        if not data_df.empty:
            loaded_station_ids = data_df["station_id"].astype(str).unique().tolist()
            metadata_df = self._filter_reference_by_station_id(metadata_df, "station_id", loaded_station_ids)
            station_col = "station_id" if "station_id" in stations_info_df.columns else "code_station"
            stations_info_df = self._filter_reference_by_station_id(stations_info_df, station_col, loaded_station_ids)
            sites_info_df = self._filter_reference_by_station_id(sites_info_df, "station_id", loaded_station_ids)

        return LocalLoadResult(
            stations_info=stations_info_df,
            sites_info=sites_info_df,
            metadata=metadata_df,
            data=data_df,
            missing_data_summary=missing_df,
            stations=all_stations,
        )

    def _load_reference_tables(self) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Load optional summary/reference CSV files from ``local_data_dir``."""
        metadata_path = self.local_data_dir / "metadata.csv"
        stations_info_path = self.local_data_dir / "stations_info.csv"
        sites_info_path = self.local_data_dir / "sites_info.csv"
        missing_path = self.local_data_dir / "missing_data_summary.csv"

        metadata_df = self._read_optional_csv(metadata_path)
        stations_info_df = self._read_optional_csv(stations_info_path)
        sites_info_df = self._read_optional_csv(sites_info_path)
        missing_df = self._read_optional_csv(missing_path)
        return metadata_df, stations_info_df, sites_info_df, missing_df

    def _find_station_file(self, station_id: str) -> Optional[Path]:
        """Resolve the best matching station CSV file for one station id."""
        candidates = sorted(self.local_data_dir.glob(f"{station_id}_*.csv"))
        if not candidates:
            exact = self.local_data_dir / f"{station_id}.csv"
            if exact.exists():
                candidates = [exact]
        if not candidates:
            return None
        return candidates[0]

    @staticmethod
    def _extract_station_metadata(station_id: str, metadata_df: pd.DataFrame) -> dict:
        """Extract one station metadata row as a plain dictionary."""
        if metadata_df.empty or "station_id" not in metadata_df.columns:
            return {}
        station_meta_row = metadata_df[metadata_df["station_id"].astype(str) == str(station_id)]
        if station_meta_row.empty:
            return {}
        return station_meta_row.iloc[0].to_dict()

    def _resolve_analysis_date_range(
        self,
        *,
        station_id: str,
        station_data: pd.DataFrame,
        metadata_df: pd.DataFrame,
    ):
        """Resolve start/end dates used for completeness diagnostics."""
        start_date = self.date_start
        end_date = self.date_end

        if (start_date is None or end_date is None) and not metadata_df.empty and "station_id" in metadata_df.columns:
            station_meta = metadata_df[metadata_df["station_id"].astype(str) == str(station_id)]
            if not station_meta.empty:
                if start_date is None and "start_date" in station_meta.columns:
                    start_date = self._to_datetime_or_none(station_meta.iloc[0].get("start_date"))
                if end_date is None and "end_date" in station_meta.columns:
                    end_date = self._to_datetime_or_none(station_meta.iloc[0].get("end_date"))

        if "date_obs_elab" in station_data.columns:
            date_series = pd.to_datetime(station_data["date_obs_elab"], errors="coerce").dropna()
            if not date_series.empty:
                if start_date is None:
                    start_date = date_series.min().to_pydatetime()
                if end_date is None:
                    end_date = date_series.max().to_pydatetime()

        return start_date, end_date

    @staticmethod
    def _enrich_station_metadata_with_coordinates(
        *,
        station_id: str,
        station_metadata: Mapping[str, Any],
        stations_info: pd.DataFrame,
    ) -> dict:
        """Fill missing coordinate fields from station reference table."""
        enriched = dict(station_metadata) if station_metadata else {}

        has_wgs84 = (
            Station._as_float_or_none(enriched.get("x_wgs84")) is not None
            and Station._as_float_or_none(enriched.get("y_wgs84")) is not None
        )
        has_l93 = (
            Station._as_float_or_none(enriched.get("x_l93")) is not None
            and Station._as_float_or_none(enriched.get("y_l93")) is not None
        )
        if has_wgs84 and has_l93:
            return enriched
        if stations_info.empty:
            return enriched

        station_col = "station_id" if "station_id" in stations_info.columns else "code_station"
        if station_col not in stations_info.columns:
            return enriched

        station_rows = stations_info[stations_info[station_col].astype(str) == str(station_id)]
        if station_rows.empty:
            return enriched
        station_info_row = station_rows.iloc[0]

        if not has_wgs84:
            if "longitude_station" in station_info_row.index and "latitude_station" in station_info_row.index:
                enriched["x_wgs84"] = station_info_row.get("longitude_station")
                enriched["y_wgs84"] = station_info_row.get("latitude_station")
        if not has_l93:
            if "coordonnee_x_station" in station_info_row.index and "coordonnee_y_station" in station_info_row.index:
                enriched["x_l93"] = station_info_row.get("coordonnee_x_station")
                enriched["y_l93"] = station_info_row.get("coordonnee_y_station")

        return enriched

