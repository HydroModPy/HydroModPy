"""Abstract base class for variable managers."""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.data_managers.common.io_helpers import safe_file_token
from hydromodpy.data_managers.common.validation import compute_completeness
from hydromodpy.data_managers.contracts.location import StationLocation
from hydromodpy.data_managers.contracts.timeseries import PointRecord


# Map VARIABLE_NAME to file prefix used in naming convention.
_VAR_FILE_PREFIX = {
    "hydrometry": "hydrometry",
    "piezometry": "piezometry",
    "water_quality": "waterquality",
}


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
        data_dir: Path | None = None,
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.project_period = project_period
        self.data_dir = Path(data_dir) if data_dir else None

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
        self._register_records(results)
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

    # ------------------------------------------------------------------
    # Persistence: save API results as CSV and register in catalog
    # ------------------------------------------------------------------

    def _persist_api_records(
        self, records: list[PointRecord], source: str,
    ) -> None:
        """Save API records as CSV files in data_dir and register in catalog."""
        if self.data_dir is None or not records:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        prefix = _VAR_FILE_PREFIX.get(self.VARIABLE_NAME, self.VARIABLE_NAME)

        for r in records:
            # Save chronicle CSV
            safe_id = safe_file_token(r.station_id)
            start_str = r.date_start.strftime("%Y%m%d")
            end_str = r.date_end.strftime("%Y%m%d")
            filename = (
                f"{prefix}_{source}_{safe_id}_{start_str}_{end_str}_{r.frequency}.csv"
            )
            filepath = self.data_dir / filename
            r.data.to_csv(filepath, index=False)

            # Update LOC file with station location
            if r.location:
                self._upsert_api_loc(r.location, source)

            # Register in catalog
            self._register_one(r, filepath)

    def _upsert_api_loc(self, loc: StationLocation, source: str) -> None:
        """Add or update a station in the API LOC file."""
        if self.data_dir is None:
            return
        prefix = _VAR_FILE_PREFIX.get(self.VARIABLE_NAME, self.VARIABLE_NAME)
        loc_path = self.data_dir / f"{prefix}_{source}_LOC.csv"

        existing: dict[str, dict] = {}
        if loc_path.exists():
            df = pd.read_csv(loc_path)
            for _, row in df.iterrows():
                existing[str(row["id"])] = row.to_dict()

        # Flatten metadata for CSV columns
        row_data = {"id": loc.id, "x": loc.x, "y": loc.y, "crs": loc.crs}
        for k, v in loc.metadata.items():
            if v is not None:
                row_data[k] = v
        existing[loc.id] = row_data

        out = pd.DataFrame(existing.values())
        out.to_csv(loc_path, index=False)

    # ------------------------------------------------------------------
    # Catalog registration
    # ------------------------------------------------------------------

    def _register_records(self, records: list[PointRecord]) -> None:
        """Register all records in the catalog (metadata only)."""
        if self.catalog is None:
            return
        for r in records:
            # For custom records loaded from user files, we don't have a
            # single file_path readily available.  Skip registration for
            # records that were already registered in _persist_api_records.
            if r.source != "custom":
                continue
            # Register custom records with a sentinel path (the source dir).
            # This lets cache_info() show what custom data is loaded.
            self._register_one(r, file_path=Path("custom"))

    def _register_one(self, r: PointRecord, file_path: Path) -> None:
        """Register a single record in the catalog."""
        if self.catalog is None:
            return
        bbox = None
        crs = None
        if r.location:
            bbox = (r.location.x, r.location.y, r.location.x, r.location.y)
            crs = r.location.crs
        self.catalog.register(
            variable=self.VARIABLE_NAME,
            source=r.source,
            station_id=r.station_id,
            file_path=str(file_path),
            date_start=r.date_start,
            date_end=r.date_end,
            unit=r.unit,
            frequency=r.frequency,
            bbox=bbox,
            crs=crs,
            is_custom=(r.source == "custom"),
        )

    # ------------------------------------------------------------------
    # Cache lookup for API data
    # ------------------------------------------------------------------

    def _load_cached_api_record(
        self,
        *,
        source: str,
        station_id: str,
    ) -> PointRecord | None:
        """Try to load a single station from cached CSV via the catalog."""
        if self.catalog is None or self.data_dir is None:
            return None
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=station_id,
            date_start=self.project_period[0] if self.project_period else None,
            date_end=self.project_period[1] if self.project_period else None,
        )
        if entry is None:
            return None

        filepath = Path(entry.file_path)
        if not filepath.exists():
            return None

        from hydromodpy.data_managers.common.io_helpers import read_timeseries_csv
        df = read_timeseries_csv(filepath)
        if df.empty:
            return None

        # Reconstruct location from LOC file if available
        location = self._load_cached_location(source, station_id)

        return PointRecord(
            station_id=station_id,
            variable=entry.variable or self.VARIABLE_NAME,
            source=source,
            unit=entry.unit or "",
            frequency=entry.frequency or "D",
            data=df,
            date_start=df["datetime"].min().to_pydatetime(),
            date_end=df["datetime"].max().to_pydatetime(),
            location=location,
        )

    def _load_cached_location(
        self, source: str, station_id: str,
    ) -> StationLocation | None:
        """Load a station's location from the API LOC file."""
        if self.data_dir is None:
            return None
        prefix = _VAR_FILE_PREFIX.get(self.VARIABLE_NAME, self.VARIABLE_NAME)
        loc_path = self.data_dir / f"{prefix}_{source}_LOC.csv"
        if not loc_path.exists():
            return None
        df = pd.read_csv(loc_path)
        row = df[df["id"].astype(str) == str(station_id)]
        if row.empty:
            return None
        r = row.iloc[0]
        extra = {k: v for k, v in r.items() if k not in ("id", "x", "y", "crs") and pd.notna(v)}
        return StationLocation(
            id=str(r["id"]), x=float(r["x"]), y=float(r["y"]),
            crs=str(r.get("crs", "EPSG:4326")), metadata=extra,
        )

    # ------------------------------------------------------------------
    # Reporting and export
    # ------------------------------------------------------------------

    def get_completeness_report(self, records: list[PointRecord]) -> pd.DataFrame:
        """Compute per-station completeness stats."""
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
