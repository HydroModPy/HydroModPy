"""Abstract base class for station/point variable managers."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.io_helpers import safe_file_token
from hydromodpy.data.contracts.completeness import compute_completeness
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.managers.base_manager_common import BaseManagerCommon, SourceContext
from hydromodpy.data.provenance.sidecars import (
    load_sidecar,
    sidecar_path_for,
    unlink_with_sidecar,
)
from hydromodpy.data.registry.constants import (
    SENTINEL_CUSTOM,
    SENTINEL_EMPTY,
)

logger = get_logger(__name__)


# Map VARIABLE_NAME to file prefix used in naming convention.
_VAR_FILE_PREFIX = {
    "hydrometry": "hydrometry",
    "intermittency": "intermittency",
    "piezometry": "piezometry",
    "water_quality": "waterquality",
}


def _chronicle_sidecar(path: Path) -> dict[str, str | None]:
    """The chronicle fields of the sidecar next to ``path``; empty when there is none."""
    if not sidecar_path_for(path).is_file():
        return {}
    try:
        sidecar = load_sidecar(path)
    except (OSError, ValueError) as exc:
        logger.debug("Unreadable sidecar next to %s: %s", path, exc)
        return {}
    return {
        "unit": sidecar.unit,
        "source_unit": sidecar.source_unit,
        "frequency": sidecar.frequency,
    }


class BaseVariableManager(BaseManagerCommon):
    """Base orchestrator inherited by each station-based variable manager.

    Subclasses set ``VARIABLE_NAME``, ``INTERNAL_UNIT`` and ``SOURCES``. A
    ``SOURCES`` function has the form
    ``fetch(cfg, *, bbox, station_ids, start, end, context)``; the station cache
    decides which stations and which periods it is asked for.
    """

    RECORD_VARIABLE: ClassVar[str | None] = None
    """The name of each record a custom file yields; the variable name when unset."""

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
        """Warn if any loaded station falls outside project_extent, read in WGS84."""
        if self.project_extent is None:
            return
        from shapely.geometry import box

        from hydromodpy.data.common.geo_helpers import filter_locations_by_geometry
        from hydromodpy.data.common.source_extent import STATION_EXTENT_CRS

        located = [r.location for r in records if r.location is not None]
        inside = filter_locations_by_geometry(
            located, box(*self.project_extent), geometry_crs=STATION_EXTENT_CRS
        )
        inside_ids = {location.id for location in inside}
        outside = [
            r.station_id
            for r in records
            if r.location is not None and r.location.id not in inside_ids
        ]
        if outside:
            warnings.warn(
                f"{self.VARIABLE_NAME}: {len(outside)} station(s) outside "
                f"project_extent {self.project_extent}: {outside}",
                stacklevel=2,
            )

    def load_custom(self, source_cfg: Any) -> list[PointRecord]:
        """Load a folder of station chronicles and their locations."""
        from hydromodpy.data.ingest.custom_points import load_custom_points

        records = load_custom_points(
            data_dir=Path(source_cfg.path),
            variable_name=self.VARIABLE_NAME,
            internal_unit=self.INTERNAL_UNIT,
            project_period=self.project_period,
            col_id=source_cfg.col_id,
            col_x=source_cfg.col_x,
            col_y=source_cfg.col_y,
            col_crs=source_cfg.col_crs,
            default_crs=source_cfg.default_crs,
            col_datetime=source_cfg.col_datetime,
            col_value=source_cfg.col_value,
            station_ids=source_cfg.station_ids,
            default_unit=None,
            record_variable=self.RECORD_VARIABLE or self.VARIABLE_NAME,
            source_unit_override=source_cfg.source_unit,
        )
        return self._apply_mask(records, source_cfg)

    def _source_context(self, source_cfg: Any) -> SourceContext:
        context = super()._source_context(source_cfg)
        if not getattr(source_cfg, "nearest", False):
            return context
        return replace(context, nearest_to=self._resolve_nearest_to(source_cfg))

    def _fetch_listed_source(self, fetch, source_cfg: Any) -> list[PointRecord]:
        context = self._source_context(source_cfg)
        bbox = self._resolve_bbox(source_cfg)

        def _fetch_for(station_ids, start, end) -> list[PointRecord]:
            return fetch(
                source_cfg,
                bbox=bbox,
                station_ids=station_ids,
                start=start,
                end=end,
                context=context,
            )

        return self._fetch_with_station_cache(source_cfg, _fetch_for, source_name=source_cfg.source)

    # ------------------------------------------------------------------
    # Bbox resolution and spatial mask (station APIs expect WGS84)
    # ------------------------------------------------------------------

    def _load_mask_geometry(self, mask_path: Path):
        """Station APIs expect WGS84, so reproject to lon/lat."""
        from hydromodpy.data.common.source_extent import mask_geometry_wgs84

        return mask_geometry_wgs84(mask_path)

    def _apply_mask(
        self,
        records: list[PointRecord],
        source_cfg,
    ) -> list[PointRecord]:
        """Filter records by spatial mask (reprojected to WGS84).

        ``nearest=True`` explicitly asks for the closest station even when it
        lies outside the watershed mask (typical for piezometers). The mask is
        still used by ``_resolve_bbox`` for API discovery, but we keep the
        fallback record instead of stripping it here.
        """
        if source_cfg.mask_path and getattr(source_cfg, "nearest", False):
            return records
        return super()._apply_mask(records, source_cfg)

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
    # Station cache: partial coverage detection + merge
    # ------------------------------------------------------------------

    def _fetch_with_station_cache(
        self,
        source_cfg: Any,
        fetch_fn: Callable[[list[str] | None, datetime, datetime], list[PointRecord]],
        *,
        source_name: str,
    ) -> list[PointRecord]:
        """Fetch station records, downloading only what the cache lacks.

        ``fetch_fn(station_ids, start, end)`` calls the provider; ``None`` as
        station ids asks it to discover stations in the extent. Stations named
        in the config are read from the cache, completed for the periods it
        misses, and a station known to have no data is not asked again.
        Discovery by extent is never cached.
        """
        if self.project_period is None:
            raise ValueError(f"project_period required to fetch {self.VARIABLE_NAME} stations.")

        station_ids = list(source_cfg.station_ids or [])
        max_stations = getattr(source_cfg, "max_stations", None)
        if station_ids and max_stations is not None:
            station_ids = station_ids[:max_stations]

        if not station_ids or source_cfg.force_refresh:
            records = fetch_fn(station_ids or None, *self.project_period)
            self._persist_api_records(records, source_name)
            return self._apply_mask(records, source_cfg)

        ready: list[PointRecord] = []
        missing_ids: list[str] = []
        to_persist: list[PointRecord] = []
        for sid in station_ids:
            if self._is_empty_sentinel(source=source_name, station_id=sid):
                logger.debug("%s station without data (cached): %s", source_name, sid)
                continue
            rec = self._load_cached_api_record(source=source_name, station_id=sid)
            if rec is None:
                missing_ids.append(sid)
                continue
            gaps = self._compute_missing_periods(rec.date_start, rec.date_end)
            if not gaps:
                ready.append(rec)
                logger.debug("%s cache hit: %s", source_name, sid)
                continue
            parts: list[PointRecord] = []
            for gap_start, gap_end in gaps:
                parts.extend(fetch_fn([sid], gap_start, gap_end))
            if parts:
                merged = self._merge_into_record(rec, *parts)
                ready.append(merged)
                to_persist.append(merged)
                logger.debug("%s cache merge: %s (+%d period(s))", source_name, sid, len(gaps))
            else:
                ready.append(rec)

        if to_persist:
            self._persist_api_records(to_persist, source_name)
        if not missing_ids:
            return self._apply_mask(ready, source_cfg)

        records = fetch_fn(missing_ids, *self.project_period)
        self._persist_api_records(records, source_name)
        fetched_ids = {r.station_id for r in records}
        empty_ids = [sid for sid in missing_ids if sid not in fetched_ids]
        if empty_ids:
            self._register_empty_api_stations(empty_ids, source_name)
        return self._apply_mask(ready + records, source_cfg)

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
            source_unit=base.source_unit or (others[0].source_unit if others else None),
        )

    # ------------------------------------------------------------------
    # Persistence: save API results as CSV and register in catalog
    # ------------------------------------------------------------------

    def _persist_api_records(
        self,
        records: list[PointRecord],
        source: str,
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
            filename = f"{prefix}_{source}_{safe_id}_{start_str}_{end_str}_{r.frequency}.csv"
            filepath = self.data_dir / filename
            r.data.to_csv(filepath, index=False)

            # Update LOC file with station location
            if r.location:
                self._upsert_api_loc(r.location, source)

            self._register_one(r, filepath)

    def _cleanup_old_api_file(self, source: str, station_id: str) -> None:
        """Delete old API CSV if a previous download exists for this station."""
        if self.catalog is None:
            return
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=station_id,
        )
        if entry is None or entry.file_path in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
            return
        unlink_with_sidecar(self._resolve_catalog_path(entry.file_path))

    def _resolve_catalog_path(self, file_path: str) -> Path:
        """Resolve a catalog file_path the way the catalog stored it."""
        return self.catalog.resolve_path(file_path, variable=self.VARIABLE_NAME)

    def _register_empty_api_stations(
        self,
        station_ids: list[str],
        source: str,
    ) -> None:
        """Register stations that returned no data from the API.

        Creates a catalog entry with file_path=SENTINEL_EMPTY so that subsequent
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
                file_path=SENTINEL_EMPTY,
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
        return entry is not None and entry.file_path == SENTINEL_EMPTY

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
            fp = r.file_path if r.file_path is not None else Path(SENTINEL_CUSTOM)
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
        self.catalog.register(
            variable=self.VARIABLE_NAME,
            source=r.source,
            station_id=r.station_id,
            file_path=str(file_path),
            date_start=r.date_start,
            date_end=r.date_end,
            unit=r.unit,
            source_unit=r.source_unit,
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
        """Try to load a single station from cached CSV via the catalog.

        Does NOT filter by date - returns whatever is cached. The caller
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
            # File deleted externally - clean up stale entry
            self.catalog.invalidate(
                variable=self.VARIABLE_NAME,
                source=source,
                station_id=station_id,
            )
            return None

        # Check if file was modified externally (mtime mismatch)
        if entry.file_mtime is not None:
            current_mtime = filepath.stat().st_mtime
            if abs(current_mtime - entry.file_mtime) > 1.0:
                # File modified externally - invalidate and re-fetch
                self.catalog.invalidate(
                    variable=self.VARIABLE_NAME,
                    source=source,
                    station_id=station_id,
                )
                return None

        from hydromodpy.data.common.io_helpers import read_timeseries_csv

        df = read_timeseries_csv(filepath)
        if df.empty:
            return None

        # Reconstruct location from LOC file if available
        location = self._load_cached_location(source, station_id)
        # The sidecar speaks for the file; the index row fills what it lacks.
        sidecar = _chronicle_sidecar(filepath)

        return PointRecord(
            station_id=station_id,
            variable=self.VARIABLE_NAME,
            source=source,
            unit=sidecar.get("unit") or entry.unit or "",
            frequency=sidecar.get("frequency") or entry.frequency or "D",
            data=df,
            date_start=df["datetime"].min().to_pydatetime(),
            date_end=df["datetime"].max().to_pydatetime(),
            location=location,
            source_unit=sidecar.get("source_unit") or entry.source_unit,
        )

    def _load_cached_location(
        self,
        source: str,
        station_id: str,
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
            id=str(r["id"]),
            x=float(r["x"]),
            y=float(r["y"]),
            crs=str(r.get("crs", "EPSG:4326")),
            metadata=extra,
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
                rec.data,
                station_id=rec.station_id,
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
        from hydromodpy.data.common.export import export_records

        return export_records(
            records,
            output_dir,
            variable_name=self.VARIABLE_NAME,
            prefix=self.VARIABLE_NAME,
        )
