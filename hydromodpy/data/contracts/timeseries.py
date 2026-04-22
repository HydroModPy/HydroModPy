"""Point time-series contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data.common.validation import compute_completeness
from hydromodpy.data.contracts.location import StationLocation

REQUIRED_COLUMNS = ("datetime", "value")


@dataclass
class PointRecord:
    """Single-station time series produced by any loader.

    data must contain at least columns [datetime, value].
    """

    station_id: str
    variable: str
    source: str
    unit: str
    frequency: str
    data: pd.DataFrame
    date_start: datetime
    date_end: datetime
    location: StationLocation | None = None
    is_constant: bool = False
    file_path: Path | None = None
    source_unit: str | None = None
    quality: dict | None = None

    def __post_init__(self):
        missing = [c for c in REQUIRED_COLUMNS if c not in self.data.columns]
        if missing:
            raise ValueError(
                f"PointRecord.data missing columns: {missing}. Got: {list(self.data.columns)}"
            )
        self.data["datetime"] = pd.to_datetime(self.data["datetime"], errors="coerce")
        self.data["value"] = pd.to_numeric(self.data["value"], errors="coerce")

        if self.quality is None and not self.data.empty:
            stats = compute_completeness(
                self.data,
                start_date=self.date_start,
                end_date=self.date_end,
                station_id=self.station_id,
            )
            self.quality = {
                "completeness_pct": stats["completeness_pct"],
                "n_expected": stats["expected_days"],
                "n_actual": stats["actual_days"],
                "n_missing": stats["missing_days"],
                "n_gaps": stats["gaps_detected"],
            }

    @property
    def n_records(self) -> int:
        return len(self.data)

    @property
    def has_data(self) -> bool:
        return not self.data.empty

    def filter_by_period(self, start: datetime, end: datetime) -> PointRecord:
        """Return a new PointRecord filtered to [start, end]."""
        mask = (self.data["datetime"] >= pd.Timestamp(start)) & (
            self.data["datetime"] <= pd.Timestamp(end)
        )
        return PointRecord(
            station_id=self.station_id,
            variable=self.variable,
            source=self.source,
            unit=self.unit,
            frequency=self.frequency,
            data=self.data.loc[mask].copy(),
            date_start=start,
            date_end=end,
            location=self.location,
            is_constant=self.is_constant,
            file_path=self.file_path,
            source_unit=self.source_unit,
        )
