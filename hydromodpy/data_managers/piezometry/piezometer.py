"""Piezometer object for single-station piezometric time series operations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple, Union

import pandas as pd

try:
    from ..common.base_station import BaseStation
except ImportError:
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    if str(_manager_root) not in sys.path:
        sys.path.insert(0, str(_manager_root))
    from common.base_station import BaseStation


class Piezometer(BaseStation):
    """Single piezometer series with piezometer-level operations."""

    def __init__(
        self,
        *,
        piezometer_id: str,
        measurement: str,
        data: Optional[pd.DataFrame] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        station_position: Optional[Mapping[str, Any]] = None,
        georeferencing: Optional[Mapping[str, Any]] = None,
    ):
        self.piezometer_id = str(piezometer_id)
        self.measurement = str(measurement)
        self.metadata = dict(metadata) if metadata else {}
        inferred_position, inferred_georef = self.infer_spatial_info(self.metadata)
        self.station_position = dict(station_position) if station_position is not None else inferred_position
        self.georeferencing = dict(georeferencing) if georeferencing is not None else inferred_georef
        self.data = pd.DataFrame() if data is None else data.copy()
        if not self.data.empty:
            self.data = self._sanitize_loaded_data(self.data)

    @staticmethod
    def infer_spatial_info(metadata: Mapping[str, Any]) -> Tuple[dict, dict]:
        """Infer station coordinates and georeferencing flags from metadata."""
        return BaseStation.infer_spatial_info(metadata)

    @staticmethod
    def _sanitize_loaded_data(df: pd.DataFrame) -> pd.DataFrame:
        """Ensure standard dtypes and required columns for loaded piezometer data."""
        return BaseStation.sanitize_dataframe(
            df,
            date_columns=["date_measure"],
            numeric_columns=["groundwater_level_m", "groundwater_depth_m"],
        )

    @staticmethod
    def _parse_datetime_column(series: pd.Series) -> pd.Series:
        """Parse datetime column supporting ISO strings and Unix timestamps in ms/s."""
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().any():
            dt_ms = pd.to_datetime(numeric, unit="ms", errors="coerce")
            dt_s = pd.to_datetime(numeric, unit="s", errors="coerce")
            out = dt_ms.where(dt_ms.notna(), dt_s)
            return out.where(out.notna(), pd.to_datetime(series, errors="coerce"))
        return pd.to_datetime(series, errors="coerce")

    @staticmethod
    def filter_by_date_range(
        df: pd.DataFrame,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Filter piezometer dataframe using date range when possible."""
        return BaseStation.filter_by_date_range(
            df,
            date_column="date_measure",
            date_start=date_start,
            date_end=date_end,
        )

    @staticmethod
    def process_api_dataframe(
        df: pd.DataFrame,
        *,
        measurement: str,
        piezometer_id: str,
    ) -> pd.DataFrame:
        """Process and clean raw API dataframe for one piezometer."""
        out = pd.DataFrame()
        if "date_measure" in df.columns:
            out["date_measure"] = df["date_measure"]
        elif "date_mesure" in df.columns:
            out["date_measure"] = df["date_mesure"]
        elif "timestamp_mesure" in df.columns:
            out["date_measure"] = df["timestamp_mesure"]
        else:
            out["date_measure"] = pd.NaT

        out["date_measure"] = Piezometer._parse_datetime_column(out["date_measure"])
        out["groundwater_level_m"] = pd.to_numeric(df.get("niveau_nappe_eau"), errors="coerce")
        out["groundwater_depth_m"] = pd.to_numeric(df.get("profondeur_nappe"), errors="coerce")
        out["qualification"] = df.get("libelle_qualification")
        out["piezometer_id"] = str(piezometer_id)

        out = out.dropna(subset=["date_measure"])
        if measurement == "level":
            out = out.dropna(subset=["groundwater_level_m"])
        elif measurement == "depth":
            out = out.dropna(subset=["groundwater_depth_m"])
        else:
            out = out.dropna(subset=["groundwater_level_m", "groundwater_depth_m"], how="all")
        return out.sort_values("date_measure").reset_index(drop=True)

    @staticmethod
    def compute_missing_data(
        df: pd.DataFrame,
        *,
        start_date: datetime,
        end_date: datetime,
        piezometer_id: str,
        verbose: bool = True,
    ) -> dict:
        """Compute missing-data summary for one piezometer within a date range."""
        return BaseStation.compute_missing_data(
            df,
            date_column="date_measure",
            start_date=start_date,
            end_date=end_date,
            id_field="piezometer_id",
            id_value=piezometer_id,
            verbose=verbose,
        )

    def completeness(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        verbose: bool = True,
    ) -> dict:
        """Compute completeness summary for this piezometer."""
        start = start_date
        end = end_date

        if start is None:
            start = self.metadata.get("start_date")
        if end is None:
            end = self.metadata.get("end_date")
        start = self._to_datetime_or_none(start)
        end = self._to_datetime_or_none(end)

        if (start is None or end is None) and not self.data.empty and "date_measure" in self.data.columns:
            dates = pd.to_datetime(self.data["date_measure"], errors="coerce").dropna()
            if not dates.empty:
                if start is None:
                    start = dates.min().to_pydatetime()
                if end is None:
                    end = dates.max().to_pydatetime()

        if start is None or end is None:
            return {
                "piezometer_id": self.piezometer_id,
                "expected_days": 0,
                "actual_days": 0,
                "missing_days": 0,
                "completeness_pct": 0.0,
                "first_date": None,
                "last_date": None,
                "gaps_detected": 0,
            }

        return self.compute_missing_data(
            self.data,
            start_date=start,
            end_date=end,
            piezometer_id=self.piezometer_id,
            verbose=verbose,
        )

    def build_label(self) -> str:
        """Build human-readable legend label."""
        station_name = self.metadata.get("station_name")
        if station_name and str(station_name).strip():
            return f"{self.piezometer_id} - {station_name}"
        return self.piezometer_id

    def plot(
        self,
        *,
        value: str | None = None,
        output_path: Optional[Union[str, Path]] = None,
        show: bool = True,
        block: bool = True,
        figsize: tuple = (12, 4),
    ):
        """Plot one piezometer series."""
        if self.data.empty:
            raise ValueError(f"No data to plot for piezometer {self.piezometer_id}.")

        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise ImportError(
                "Matplotlib is required to plot piezometer data. "
                "Install with: pip install matplotlib"
            ) from exc

        selected_value = value or ("depth" if self.measurement == "depth" else "level")
        y_column = "groundwater_depth_m" if selected_value == "depth" else "groundwater_level_m"
        y_label = "Depth to water table [m]" if selected_value == "depth" else "Groundwater level [m]"

        if y_column not in self.data.columns:
            raise ValueError(f"Column '{y_column}' not available for piezometer {self.piezometer_id}.")

        frame = self.data.copy()
        frame["date_measure"] = pd.to_datetime(frame["date_measure"], errors="coerce")
        frame[y_column] = pd.to_numeric(frame[y_column], errors="coerce")
        frame = frame.dropna(subset=["date_measure", y_column]).sort_values("date_measure")
        if frame.empty:
            raise ValueError(f"No valid points to plot for piezometer {self.piezometer_id}.")

        fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=140)
        ax.plot(
            frame["date_measure"].to_numpy(),
            frame[y_column].to_numpy(dtype=float),
            linewidth=1.4,
            label=self.build_label(),
        )
        ax.set_title(f"Piezometer series - {self.piezometer_id}")
        ax.set_xlabel("Date")
        ax.set_ylabel(y_label)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best")
        fig.tight_layout()

        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(output_path, bbox_inches="tight")
            print(f"Piezometer figure exported to: {output_path}")

        backend = plt.get_backend().lower()
        if show:
            if "agg" in backend:
                print("Figure backend is non-interactive (Agg): closing figure without display.")
                plt.close(fig)
            else:
                plt.show(block=block)
        else:
            plt.close(fig)

        return fig, ax
