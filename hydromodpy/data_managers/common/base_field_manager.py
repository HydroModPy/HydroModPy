"""Abstract base class for grid-data variable managers (climatic variables).

Provides cache lookup, .nc persistence, catalog registration, and
subsumption cleanup for FieldRecord data (xarray Datasets from SIM2 API).

PointRecord sources (custom CSV, synthetic) pass through without caching.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from hydromodpy.data_managers.common.geo_helpers import bbox_hash
from hydromodpy.data_managers.contracts.load_result import LoadResult
from hydromodpy.data_managers.contracts.spatial_field import FieldRecord
from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.support.tools.log_manager import get_logger

logger = get_logger(__name__)


class BaseFieldManager(ABC):
    """Base orchestrator for grid-data variable managers.

    Subclasses set VARIABLE_NAME, INTERNAL_UNIT and implement
    ``_fetch_from_source``.
    """

    VARIABLE_NAME: str = ""
    INTERNAL_UNIT: str = ""

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

        Returns a LoadResult separating point records from gridded fields.
        """
        result = LoadResult()
        for source_cfg in self.config.sources:
            records = self._fetch_from_source(source_cfg)
            if not isinstance(records, list):
                records = [records]
            for rec in records:
                if isinstance(rec, FieldRecord):
                    result.fields.append(rec)
                else:
                    result.points.append(rec)
        self._register_point_records(result.points)
        return result

    @abstractmethod
    def _fetch_from_source(self, source_cfg: Any) -> list[FieldRecord | PointRecord]:
        """Dispatch to the right loader (custom, API, synthetic)."""
        ...

    # ------------------------------------------------------------------
    # Bbox resolution and spatial mask (shared by all managers)
    # ------------------------------------------------------------------

    def _resolve_bbox(self, source_cfg) -> tuple | None:
        if source_cfg.mask_path:
            from hydromodpy.data_managers.common.geo_helpers import (
                geometry_to_bbox,
                load_mask_geometry,
            )
            geom = load_mask_geometry(source_cfg.mask_path)
            return geometry_to_bbox(geom)
        if source_cfg.extent and self.project_extent:
            return self.project_extent
        return None

    def _apply_mask(
        self, records: list[PointRecord], source_cfg,
    ) -> list[PointRecord]:
        if not source_cfg.mask_path:
            return records
        from hydromodpy.data_managers.common.geo_helpers import (
            filter_locations_by_geometry,
            load_mask_geometry,
        )
        geom = load_mask_geometry(source_cfg.mask_path)
        locs_to_check = [r.location for r in records if r.location is not None]
        inside = filter_locations_by_geometry(locs_to_check, geom)
        valid_ids = {loc.id for loc in inside}
        return [
            r for r in records
            if r.location is None or r.station_id in valid_ids
        ]

    def _handle_custom_results(self, records: list, source_cfg) -> list:
        """Dispatch custom results: mask PointRecords, register FieldRecords."""
        point_records = [r for r in records if isinstance(r, PointRecord)]
        field_records = [r for r in records if isinstance(r, FieldRecord)]
        result: list = []
        if point_records:
            result.extend(self._apply_mask(point_records, source_cfg))
        if field_records:
            self._register_custom_fields(field_records)
            result.extend(field_records)
        return result

    # ------------------------------------------------------------------
    # Grid cache: check catalog → load .nc or fetch API → persist
    # ------------------------------------------------------------------

    def _load_or_fetch_fields(
        self,
        source_cfg,
        source_name: str,
        fetch_fn,
        *,
        variable_names: list[str] | None = None,
    ) -> list[FieldRecord]:
        """Smart cache for SIM2 grid data.

        1. Check catalog for a cached .nc covering the requested bbox+dates.
        2. If hit → load from .nc.
        3. If miss → call *fetch_fn*, persist as .nc, register, subsume.

        Parameters
        ----------
        source_cfg : source config object
        source_name : e.g. "sim2"
        fetch_fn : callable(source_cfg, *, bbox, project_period) → list[FieldRecord]
        variable_names : for compound variables (precipitation, radiation),
            the list of sub-variable names to check in cache.
            If None, uses [VARIABLE_NAME].
        """
        bbox = self._resolve_bbox(source_cfg)
        if variable_names is None:
            variable_names = [self.VARIABLE_NAME]

        # --- Try cache ---
        if not source_cfg.force_refresh:
            cached = self._find_cached_fields(
                source=source_name,
                variable_names=variable_names,
                bbox=bbox,
            )
            if cached is not None:
                return cached

        # --- Fetch from API ---
        records = fetch_fn(
            source_cfg, bbox=bbox, project_period=self.project_period,
        )

        # --- Persist + register + subsume ---
        self._persist_field_records(records, source_name)

        return records

    def _find_cached_fields(
        self,
        *,
        source: str,
        variable_names: list[str],
        bbox: tuple | None,
    ) -> list[FieldRecord] | None:
        """Find cached .nc files covering the requested bbox+dates.

        Returns all cached FieldRecords if ALL variable_names are cached,
        otherwise None (partial cache = miss).
        """
        if self.catalog is None or self.data_dir is None:
            return None

        date_start = self.project_period[0] if self.project_period else None
        date_end = self.project_period[1] if self.project_period else None

        results: list[FieldRecord] = []
        for var_name in variable_names:
            entry = self.catalog.find_cached(
                variable=var_name,
                source=source,
                bbox=bbox,
                date_start=date_start,
                date_end=date_end,
            )
            if entry is None:
                return None  # partial miss → full re-fetch

            nc_path = self._resolve_nc_path(entry.file_path)
            if not nc_path.exists():
                self.catalog.invalidate(
                    variable=var_name, source=source,
                )
                return None

            import xarray as xr
            ds = xr.open_dataset(nc_path)
            logger.info("Cache hit: %s from %s", var_name, nc_path.name)

            results.append(FieldRecord(
                variable=var_name,
                source=source,
                unit=entry.unit or self.INTERNAL_UNIT,
                data=ds,
                bbox=(entry.bbox_xmin, entry.bbox_ymin,
                      entry.bbox_xmax, entry.bbox_ymax),
                crs=entry.crs or "EPSG:4326",
                date_start=datetime.fromisoformat(entry.date_start)
                if entry.date_start else None,
                date_end=datetime.fromisoformat(entry.date_end)
                if entry.date_end else None,
                frequency=entry.frequency,
                source_unit=self._extract_field_source_unit(ds, var_name) or entry.source_unit,
            ))

        return results

    def _persist_field_records(
        self,
        records: list[FieldRecord],
        source: str,
    ) -> None:
        """Save FieldRecords as .nc files, register in catalog, subsume."""
        if self.data_dir is None or not records:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)

        for rec in records:
            filename = self._nc_filename(
                rec.variable, source, rec.bbox,
                rec.date_start, rec.date_end,
            )
            nc_path = self.data_dir / filename

            # Save xarray Dataset to NetCDF
            if not rec.is_file_reference:
                rec.data.to_netcdf(nc_path)
                logger.info("Saved: %s", nc_path.name)
            else:
                # Already a file — just register the path
                nc_path = Path(rec.data)

            # Register in catalog
            entry_id = self._register_field(rec, nc_path, source)

            # Subsume smaller grids
            if self.catalog is not None:
                removed = self.catalog.subsume_entries(
                    variable=rec.variable,
                    source=source,
                    bbox=rec.bbox,
                    date_start=rec.date_start.isoformat()
                    if rec.date_start else None,
                    date_end=rec.date_end.isoformat()
                    if rec.date_end else None,
                    exclude_id=entry_id,
                )
                if removed:
                    logger.info("Subsumed %d smaller grid(s) for %s", removed, rec.variable)

    def _register_field(
        self, rec: FieldRecord, nc_path: Path, source: str,
    ) -> int | None:
        """Register a FieldRecord in the catalog. Returns entry id."""
        if self.catalog is None:
            return None
        return self.catalog.register(
            variable=rec.variable,
            source=source,
            file_path=str(nc_path),
            bbox=rec.bbox,
            crs=rec.crs,
            date_start=rec.date_start,
            date_end=rec.date_end,
            frequency=rec.frequency,
            unit=rec.unit,
            source_unit=rec.source_unit,
            is_custom=False,
        )

    def _register_point_records(self, records: list[PointRecord]) -> None:
        """Register all PointRecords in the catalog (metadata only).

        Mirrors BaseVariableManager._register_records: ensures every loaded
        station is visible in the catalog regardless of source type.
        """
        if self.catalog is None:
            return
        for r in records:
            bbox = None
            crs = None
            if r.location is not None:
                bbox = (r.location.x, r.location.y, r.location.x, r.location.y)
                crs = r.location.crs
            fp = str(r.file_path) if r.file_path is not None else r.source
            self.catalog.register(
                variable=self.VARIABLE_NAME,
                source=r.source,
                station_id=r.station_id,
                file_path=fp,
                date_start=r.date_start,
                date_end=r.date_end,
                unit=r.unit,
                source_unit=r.source_unit,
                frequency=r.frequency,
                bbox=bbox,
                crs=crs,
                is_custom=(r.source == "custom"),
            )

    def _register_custom_fields(self, records: list[FieldRecord]) -> None:
        """Register custom FieldRecords in the catalog (metadata only).

        Points to the user's original file — no copy, no subsumption.
        """
        if self.catalog is None:
            return
        for rec in records:
            file_path = str(rec.data) if rec.is_file_reference else "custom"
            self.catalog.register(
                variable=rec.variable,
                source="custom",
                file_path=file_path,
                bbox=rec.bbox,
                crs=rec.crs,
                date_start=rec.date_start,
                date_end=rec.date_end,
                frequency=rec.frequency,
                unit=rec.unit,
                source_unit=rec.source_unit,
                is_custom=True,
            )

    def _resolve_nc_path(self, file_path: str) -> Path:
        """Resolve a catalog file_path to absolute."""
        return self._resolve_data_path(file_path, self.data_dir)

    @staticmethod
    def _resolve_data_path(file_path: str, data_dir: Path | None) -> Path:
        """Resolve a catalog file_path to absolute (shared utility)."""
        p = Path(file_path)
        if p.is_absolute():
            return p
        if data_dir is not None:
            return data_dir / p
        return p

    @staticmethod
    def _extract_field_source_unit(ds, variable: str) -> str | None:
        """Extract an optional source-unit attribute from one xarray Dataset."""
        data_var = variable if variable in ds.data_vars else next(iter(ds.data_vars), None)
        if data_var is None:
            return None
        raw_value = ds[data_var].attrs.get("source_unit")
        if raw_value is None or not str(raw_value).strip():
            return None
        return str(raw_value).strip()

    @staticmethod
    def _nc_filename(
        variable: str,
        source: str,
        bbox: tuple | None,
        date_start: datetime | None,
        date_end: datetime | None,
    ) -> str:
        """Deterministic filename for a grid .nc file."""
        parts = [variable, source]
        if bbox is not None:
            parts.append(bbox_hash(bbox))
        if date_start is not None:
            parts.append(date_start.strftime("%Y%m%d"))
        if date_end is not None:
            parts.append(date_end.strftime("%Y%m%d"))
        return "_".join(parts) + ".nc"
