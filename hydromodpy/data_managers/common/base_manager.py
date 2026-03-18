"""Abstract base class for variable managers."""

from __future__ import annotations

import logging
import warnings
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.data_managers.common.io_helpers import safe_file_token
from hydromodpy.data_managers.common.validation import compute_completeness
from hydromodpy.data_managers.contracts.load_result import LoadResult
from hydromodpy.data_managers.contracts.location import StationLocation
from hydromodpy.data_managers.contracts.timeseries import PointRecord

logger = logging.getLogger(__name__)


# Map VARIABLE_NAME to file prefix used in naming convention.
_VAR_FILE_PREFIX = {
    "hydrometry": "hydrometry",
    "intermittency": "intermittency",
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

    def load(self) -> LoadResult:
        """Load data from all configured sources.

        Returns a LoadResult (points only for station-based variables).
        """
        results: list[PointRecord] = []
        for source_cfg in self.config.sources:
            records = self._fetch_from_source(source_cfg)
            if isinstance(records, list):
                results.extend(records)
            else:
                results.append(records)
        self._warn_stations_outside_extent(results)
        self._register_records(results)
        return LoadResult(points=results)

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
    # Bbox resolution and spatial mask (Hub'Eau expects WGS84)
    # ------------------------------------------------------------------

    def _resolve_bbox(self, source_cfg) -> tuple | None:
        """Get WGS84 bbox from mask or project extent (Hub'Eau expects lon/lat)."""
        if source_cfg.mask_path:
            from hydromodpy.data_managers.common.geo_helpers import (
                load_mask_geometry_wgs84, geometry_to_bbox,
            )
            geom = load_mask_geometry_wgs84(source_cfg.mask_path)
            return geometry_to_bbox(geom)
        if source_cfg.extent and self.project_extent:
            return self.project_extent
        return None

    def _apply_mask(self, records: list[PointRecord], source_cfg) -> list[PointRecord]:
        """Filter records by spatial mask (reprojected to WGS84)."""
        if not source_cfg.mask_path:
            return records
        from hydromodpy.data_managers.common.geo_helpers import (
            load_mask_geometry_wgs84, filter_locations_by_geometry,
        )
        geom = load_mask_geometry_wgs84(source_cfg.mask_path)
        locs_to_check = [r.location for r in records if r.location is not None]
        inside = filter_locations_by_geometry(locs_to_check, geom)
        valid_ids = {loc.id for loc in inside}
        return [
            r for r in records
            if r.location is None or r.station_id in valid_ids
        ]

    def _resolve_nearest_to(self, source_cfg) -> tuple[float, float] | None:
        """Compute centroid of the project extent for nearest-station search."""
        bbox = self._resolve_bbox(source_cfg)
        if bbox is None and self.project_extent is not None:
            bbox = self.project_extent
        if bbox is None:
            return None
        xmin, ymin, xmax, ymax = bbox
        return ((xmin + xmax) / 2, (ymin + ymax) / 2)

    # ------------------------------------------------------------------
    # Smart cache: partial coverage detection + merge
    # ------------------------------------------------------------------

    def _compute_missing_periods(
        self,
        cached_start: datetime,
        cached_end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        """Return date ranges from project_period not covered by the cache.

        Returns an empty list if the cache fully covers the requested period.
        """
        if self.project_period is None:
            return []
        req_start, req_end = self.project_period
        missing: list[tuple[datetime, datetime]] = []
        if req_start < cached_start:
            missing.append((req_start, cached_start - timedelta(days=1)))
        if req_end > cached_end:
            missing.append((cached_end + timedelta(days=1), req_end))
        return missing

    def _merge_into_record(
        self,
        base: PointRecord,
        *others: PointRecord,
    ) -> PointRecord:
        """Merge multiple PointRecords for the same station.

        Concatenates data, deduplicates by datetime, and sorts.
        Returns a single PointRecord covering the full period.
        """
        dfs = [base.data] + [r.data for r in others]
        merged = (
            pd.concat(dfs, ignore_index=True)
            .drop_duplicates(subset="datetime")
            .sort_values("datetime")
            .reset_index(drop=True)
        )
        return PointRecord(
            station_id=base.station_id,
            variable=base.variable,
            source=base.source,
            unit=base.unit,
            frequency=base.frequency,
            data=merged,
            date_start=merged["datetime"].min().to_pydatetime(),
            date_end=merged["datetime"].max().to_pydatetime(),
            location=base.location or (others[0].location if others else None),
        )

    # ------------------------------------------------------------------
    # Persistence: save API results as CSV and register in catalog
    # ------------------------------------------------------------------

    def _persist_api_records(
        self, records: list[PointRecord], source: str,
    ) -> None:
        """Save API records as CSV files in data_dir and register in catalog.

        If a previous CSV exists for the same station (different period),
        the old file is deleted before saving the new one.
        """
        if self.data_dir is None or not records:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        prefix = _VAR_FILE_PREFIX.get(self.VARIABLE_NAME, self.VARIABLE_NAME)

        for r in records:
            # Delete old CSV if it exists with a different filename
            self._cleanup_old_api_file(source, r.station_id)

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

            # Register in catalog (store filename only for portability)
            self._register_one(r, Path(filename))

    def _cleanup_old_api_file(self, source: str, station_id: str) -> None:
        """Delete old API CSV if a previous download exists for this station."""
        if self.catalog is None:
            return
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=station_id,
        )
        if entry is None:
            return
        old_path = self._resolve_catalog_path(entry.file_path)
        if old_path.exists():
            old_path.unlink()

    def _resolve_catalog_path(self, file_path: str) -> Path:
        """Resolve a catalog file_path to an absolute path.

        If file_path is a sentinel ("custom", "empty") or already absolute,
        return as-is. Otherwise, resolve relative to data_dir.
        """
        if file_path in ("custom", "empty"):
            return Path(file_path)
        p = Path(file_path)
        if p.is_absolute():
            return p
        if self.data_dir is not None:
            return self.data_dir / p
        return p

    def _register_empty_api_stations(
        self, station_ids: list[str], source: str,
    ) -> None:
        """Register stations that returned no data from the API.

        Creates a catalog entry with file_path="empty" so that subsequent
        runs don't re-fetch stations known to have no data.
        Use force_refresh=True to bypass this sentinel.
        """
        if self.catalog is None:
            return
        for sid in station_ids:
            self.catalog.register(
                variable=self.VARIABLE_NAME,
                source=source,
                station_id=sid,
                file_path="empty",
                is_custom=False,
            )

    def _is_empty_sentinel(self, source: str, station_id: str) -> bool:
        """Check if a station was previously marked as having no data."""
        if self.catalog is None:
            return False
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=station_id,
        )
        return entry is not None and entry.file_path == "empty"

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
            # API records are already registered in _persist_api_records.
            if r.source != "custom":
                continue
            fp = r.file_path if r.file_path is not None else Path("custom")
            self._register_one(r, file_path=fp)

    def _register_one(self, r: PointRecord, file_path: Path) -> None:
        """Register a single record in the catalog."""
        if self.catalog is None:
            return
        bbox = None
        crs = None
        if r.location:
            bbox = (r.location.x, r.location.y, r.location.x, r.location.y)
            crs = r.location.crs
        # Compute mtime from the actual file on disk (resolve relative path)
        actual_path = self._resolve_catalog_path(str(file_path))
        mtime = actual_path.stat().st_mtime if actual_path.exists() else None
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
            file_mtime=mtime,
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
        """Try to load a single station from cached CSV via the catalog.

        Does NOT filter by date — returns whatever is cached. The caller
        uses _compute_missing_periods() to detect partial coverage.
        """
        if self.catalog is None or self.data_dir is None:
            return None
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=station_id,
        )
        if entry is None:
            return None

        filepath = self._resolve_catalog_path(entry.file_path)
        if not filepath.exists():
            # File deleted externally — clean up stale entry
            self.catalog.invalidate(
                variable=self.VARIABLE_NAME, source=source, station_id=station_id,
            )
            return None

        # Check if file was modified externally (mtime mismatch)
        if entry.file_mtime is not None:
            current_mtime = filepath.stat().st_mtime
            if abs(current_mtime - entry.file_mtime) > 1.0:
                # File modified externally — invalidate and re-fetch
                self.catalog.invalidate(
                    variable=self.VARIABLE_NAME, source=source, station_id=station_id,
                )
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

    def get_completeness_report(self, records: LoadResult | list[PointRecord]) -> pd.DataFrame:
        """Compute per-station completeness stats."""
        if isinstance(records, LoadResult):
            records = records.points

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
        records: LoadResult | list[PointRecord],
        output_dir: str | Path,
    ) -> dict[str, Path]:
        """Export records to CSV (chronicles + metadata + table of contents)."""
        if isinstance(records, LoadResult):
            records = records.points
        from hydromodpy.data_managers.common.export import export_records
        return export_records(
            records, output_dir,
            variable_name=self.VARIABLE_NAME,
            prefix=self.VARIABLE_NAME,
        )
