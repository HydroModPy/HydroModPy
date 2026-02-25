"""Local piezometry loader for previously exported station files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd

try:
    from ..common.base_loaders import BaseLocalLoader
    from ..common.utils import safe_file_token
    from .piezometer import Piezometer
except ImportError:
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _manager_dir = Path(__file__).resolve().parent
    for _path in (str(_manager_root), str(_manager_dir)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_loaders import BaseLocalLoader
    from common.utils import safe_file_token
    from piezometer import Piezometer


@dataclass
class LocalLoadResult:
    """Normalized payload returned by :meth:`LocalPiezometerLoader.load`."""

    stations_info: pd.DataFrame
    metadata: pd.DataFrame
    data: pd.DataFrame
    missing_data_summary: pd.DataFrame
    piezometers: Dict[str, Piezometer]


class LocalPiezometerLoader(BaseLocalLoader):
    """Load piezometer series from local CSV exports."""

    def __init__(
        self,
        *,
        measurement: str,
        local_data_dir: Path,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ):
        self.measurement = measurement
        self.local_data_dir = Path(local_data_dir)
        self.date_start = date_start
        self.date_end = date_end

    def load(self, *, piezometer_ids: Sequence[str]) -> LocalLoadResult:
        """Load selected piezometers from local exported files."""
        print(f"Loading LOCAL data for {len(piezometer_ids)} piezometers from: {self.local_data_dir}")

        metadata_df, stations_info_df, _ = self._load_reference_tables()
        all_data = []
        all_missing_summary = []
        all_piezometers: Dict[str, Piezometer] = {}

        for idx, piezometer_id in enumerate(piezometer_ids):
            piezometer_id = str(piezometer_id)
            print(f"\n[{idx + 1}/{len(piezometer_ids)}] Loading local piezometer {piezometer_id}")
            station_file = self._find_piezometer_file(piezometer_id)
            if station_file is None:
                print(f"WARNING: local file not found for piezometer {piezometer_id}")
                continue

            try:
                station_data = pd.read_csv(station_file)
            except Exception as exc:
                print(f"WARNING: failed to read {station_file}: {exc}")
                continue

            if station_data.empty:
                print(f"WARNING: no rows in {station_file}")
                continue

            station_data = self._normalize_local_columns(station_data)
            station_data["piezometer_id"] = piezometer_id
            station_data = Piezometer.filter_by_date_range(
                station_data,
                date_start=self.date_start,
                date_end=self.date_end,
            )
            if station_data.empty:
                print(f"  No rows remaining after date filtering for {piezometer_id}")
                continue

            station_metadata = self._extract_station_metadata(piezometer_id, metadata_df)
            station_metadata = self._enrich_station_metadata_with_coordinates(
                piezometer_id=piezometer_id,
                station_metadata=station_metadata,
                stations_info=stations_info_df,
            )

            piezometer = Piezometer(
                piezometer_id=piezometer_id,
                measurement=self.measurement,
                data=station_data,
                metadata=station_metadata,
            )
            all_piezometers[piezometer_id] = piezometer
            all_data.append(piezometer.data)

            analysis_start, analysis_end = self._resolve_analysis_date_range(
                piezometer_id=piezometer_id,
                station_data=piezometer.data,
                metadata_df=metadata_df,
            )
            if analysis_start is not None and analysis_end is not None:
                all_missing_summary.append(
                    piezometer.completeness(
                        start_date=analysis_start,
                        end_date=analysis_end,
                    )
                )

        data_df = pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()
        missing_df = pd.DataFrame(all_missing_summary) if all_missing_summary else pd.DataFrame()

        if not data_df.empty:
            loaded_ids = data_df["piezometer_id"].astype(str).unique().tolist()
            metadata_df = self._filter_reference_by_station_id(metadata_df, "piezometer_id", loaded_ids)
            station_col = "piezometer_id" if "piezometer_id" in stations_info_df.columns else "code_bss"
            stations_info_df = self._filter_reference_by_station_id(stations_info_df, station_col, loaded_ids)

        return LocalLoadResult(
            stations_info=stations_info_df,
            metadata=metadata_df,
            data=data_df,
            missing_data_summary=missing_df,
            piezometers=all_piezometers,
        )

    def _load_reference_tables(self) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Load optional summary/reference CSV files from ``local_data_dir``."""
        metadata_path = self.local_data_dir / "metadata.csv"
        stations_info_path = self.local_data_dir / "stations_info.csv"
        missing_path = self.local_data_dir / "missing_data_summary.csv"

        metadata_df = self._read_optional_csv(metadata_path)
        stations_info_df = self._read_optional_csv(stations_info_path)
        missing_df = self._read_optional_csv(missing_path)
        return metadata_df, stations_info_df, missing_df

    @staticmethod
    def _safe_id_token(piezometer_id: str) -> str:
        """Normalize one piezometer identifier for filename matching."""
        return safe_file_token(piezometer_id)

    def _find_piezometer_file(self, piezometer_id: str) -> Optional[Path]:
        """Resolve the best matching piezometer CSV file for one identifier."""
        safe_id = self._safe_id_token(piezometer_id)
        candidates = sorted(self.local_data_dir.glob(f"{safe_id}_*.csv"))
        if not candidates:
            exact = self.local_data_dir / f"{safe_id}.csv"
            if exact.exists():
                candidates = [exact]
        if not candidates:
            # Compatibility fallback when id does not contain path separators.
            raw_candidates = sorted(self.local_data_dir.glob(f"{piezometer_id}_*.csv"))
            if raw_candidates:
                candidates = raw_candidates
        if not candidates:
            raw_exact = self.local_data_dir / f"{piezometer_id}.csv"
            if raw_exact.exists():
                candidates = [raw_exact]
        if not candidates:
            return None
        return candidates[0]

    @staticmethod
    def _normalize_local_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize local files to standard piezometry column names."""
        out = df.copy()
        rename_map = {}
        if "date_obs_elab" in out.columns and "date_measure" not in out.columns:
            rename_map["date_obs_elab"] = "date_measure"
        if "date_mesure" in out.columns and "date_measure" not in out.columns:
            rename_map["date_mesure"] = "date_measure"
        if "niveau_nappe_eau" in out.columns and "groundwater_level_m" not in out.columns:
            rename_map["niveau_nappe_eau"] = "groundwater_level_m"
        if "profondeur_nappe" in out.columns and "groundwater_depth_m" not in out.columns:
            rename_map["profondeur_nappe"] = "groundwater_depth_m"
        if rename_map:
            out = out.rename(columns=rename_map)
        return out

    @staticmethod
    def _extract_station_metadata(piezometer_id: str, metadata_df: pd.DataFrame) -> dict:
        """Extract one piezometer metadata row as a plain dictionary."""
        if metadata_df.empty:
            return {}
        station_col = "piezometer_id" if "piezometer_id" in metadata_df.columns else "code_bss"
        if station_col not in metadata_df.columns:
            return {}
        station_meta_row = metadata_df[metadata_df[station_col].astype(str) == str(piezometer_id)]
        if station_meta_row.empty:
            return {}
        return station_meta_row.iloc[0].to_dict()

    def _resolve_analysis_date_range(
        self,
        *,
        piezometer_id: str,
        station_data: pd.DataFrame,
        metadata_df: pd.DataFrame,
    ):
        """Resolve start/end dates used for completeness diagnostics."""
        start_date = self.date_start
        end_date = self.date_end

        if (start_date is None or end_date is None) and not metadata_df.empty:
            station_col = "piezometer_id" if "piezometer_id" in metadata_df.columns else "code_bss"
            if station_col in metadata_df.columns:
                station_meta = metadata_df[metadata_df[station_col].astype(str) == str(piezometer_id)]
                if not station_meta.empty:
                    if start_date is None and "start_date" in station_meta.columns:
                        start_date = self._to_datetime_or_none(station_meta.iloc[0].get("start_date"))
                    if end_date is None and "end_date" in station_meta.columns:
                        end_date = self._to_datetime_or_none(station_meta.iloc[0].get("end_date"))

        if "date_measure" in station_data.columns:
            date_series = pd.to_datetime(station_data["date_measure"], errors="coerce").dropna()
            if not date_series.empty:
                if start_date is None:
                    start_date = date_series.min().to_pydatetime()
                if end_date is None:
                    end_date = date_series.max().to_pydatetime()

        return start_date, end_date

    @staticmethod
    def _enrich_station_metadata_with_coordinates(
        *,
        piezometer_id: str,
        station_metadata: Mapping[str, Any],
        stations_info: pd.DataFrame,
    ) -> dict:
        """Fill missing coordinate fields from station reference table."""
        enriched = dict(station_metadata) if station_metadata else {}

        has_wgs84 = (
            Piezometer._as_float_or_none(enriched.get("x_wgs84")) is not None
            and Piezometer._as_float_or_none(enriched.get("y_wgs84")) is not None
        )
        if has_wgs84:
            return enriched
        if stations_info.empty:
            return enriched

        station_col = "piezometer_id" if "piezometer_id" in stations_info.columns else "code_bss"
        if station_col not in stations_info.columns:
            return enriched

        station_rows = stations_info[stations_info[station_col].astype(str) == str(piezometer_id)]
        if station_rows.empty:
            return enriched
        station_info_row = station_rows.iloc[0]

        if "longitude_station" in station_info_row.index and "latitude_station" in station_info_row.index:
            enriched["x_wgs84"] = station_info_row.get("longitude_station")
            enriched["y_wgs84"] = station_info_row.get("latitude_station")
        return enriched

