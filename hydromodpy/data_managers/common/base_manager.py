"""Abstract base class for variable managers."""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.data_managers.common.validation import compute_completeness
from hydromodpy.data_managers.contracts.timeseries import PointRecord


class BaseVariableManager(ABC):
    """Base orchestrator inherited by each variable manager.

    Subclasses set VARIABLE_NAME and implement _fetch_from_source.
    """

    VARIABLE_NAME: str = ""

    def __init__(
        self,
        *,
        config: Any,
        catalog: Any,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.project_period = project_period

    def load(self) -> list[PointRecord]:
        """Load data from all configured sources. Returns list of records."""
        results: list[PointRecord] = []
        for source_cfg in self.config.sources:
            records = self._fetch_from_source(source_cfg)
            if isinstance(records, list):
                results.extend(records)
            else:
                results.append(records)
        self._warn_stations_outside_extent(results)
        return results

    def _warn_stations_outside_extent(self, records: list[PointRecord]) -> None:
        """Warn if any loaded stations fall outside project_extent."""
        if self.project_extent is None:
            return
        xmin, ymin, xmax, ymax = self.project_extent
        outside = []
        for r in records:
            if r.location is None:
                continue
            x, y = r.location.x, r.location.y
            if not (xmin <= x <= xmax and ymin <= y <= ymax):
                outside.append(r.station_id)
        if outside:
            warnings.warn(
                f"{self.VARIABLE_NAME}: {len(outside)} station(s) outside "
                f"project_extent {self.project_extent}: {outside}",
                stacklevel=2,
            )

    @abstractmethod
    def _fetch_from_source(self, source_cfg: Any) -> Any:
        """Dispatch to the right loader (custom or API)."""
        ...

    def get_completeness_report(self, records: list[PointRecord]) -> pd.DataFrame:
        """Compute per-station completeness stats.

        Returns a DataFrame with columns: station_id, expected_days,
        actual_days, missing_days, completeness_pct, first_date,
        last_date, gaps_detected.
        """
        start = self.project_period[0] if self.project_period else None
        end = self.project_period[1] if self.project_period else None

        rows = []
        for rec in records:
            stats = compute_completeness(
                rec.data, station_id=rec.station_id,
                start_date=start or rec.date_start,
                end_date=end or rec.date_end,
            )
            stats["variable"] = rec.variable
            stats["source"] = rec.source
            stats["is_constant"] = rec.is_constant
            rows.append(stats)

        return pd.DataFrame(rows)

    def export(
        self,
        records: list[PointRecord],
        output_dir: str | Path,
    ) -> dict[str, Path]:
        """Export records to CSV (chronicles + metadata + table of contents)."""
        from hydromodpy.data_managers.common.export import export_records
        return export_records(
            records, output_dir,
            variable_name=self.VARIABLE_NAME,
            prefix=self.VARIABLE_NAME,
        )
