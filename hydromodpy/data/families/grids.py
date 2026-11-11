"""Abstract base class for the grid-data (field) variables."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from hydromodpy.core.exceptions import DataProductError
from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.geometry import bbox_hash
from hydromodpy.data.common.source_extent import resolve_source_extent
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.families.common import VariableBase
from hydromodpy.data.provenance.sidecars import CacheRow
from hydromodpy.data.source.port import FetchRequest, FetchResult, Period

logger = get_logger(__name__)


def records_of(result: FetchResult) -> list[FieldRecord | PointRecord]:
    """The records a field variable holds, refusing a payload it cannot hold.

    An empty list is an answer, and the caller decides what it means.
    """
    if result.kind == "fields":
        return list(result.fields)
    if result.kind == "points":
        return list(result.points)
    raise DataProductError(
        f"Source {result.source_id!r} answered a field variable with a {result.kind!r} "
        "payload. A field variable holds grids or station chronicles, and the sources "
        "registered under its section serve exactly that."
    )


class GridVariable(VariableBase):
    """Base orchestrator for grid-data variables.

    Subclasses set ``VARIABLE_NAME`` and ``INTERNAL_UNIT``; the source a section
    names is a class of the data-source port, and this family translates its
    call into one :class:`~hydromodpy.data.source.port.FetchRequest`: the extent
    the mask or the project extent resolves to, in the CRS it is really in, and
    the run's period. A source that declares no selector gets neither: a
    computed constant or a synthetic recharge reads nothing spatial.

    The variable keeps the grid cache, and it is the one thing the port says
    nothing about: a field source that selects by extent and answers fields a
    grid can be cut from is a download, and its answers are keyed on the box and
    the window and reused. A source that reads a file the section names
    (Explore2) is read again at each run, and a source that keeps its own cache
    (SHOM) or computes from the section alone is never cached here.
    """

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
        return result

    def load_file(self, source_cfg: Any) -> list[FieldRecord | PointRecord]:
        """Load a folder of chronicles, a NetCDF or a GeoTIFF of the user."""
        from hydromodpy.data.ingest.custom_points import load_file_multiformat

        records = load_file_multiformat(
            Path(source_cfg.path),
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
            default_unit=self.INTERNAL_UNIT,
            source_unit=source_cfg.source_unit,
            grid_crs=getattr(source_cfg, "crs", None),
            grid_nodata=getattr(source_cfg, "nodata", None),
        )
        return self._handle_file_results(records, source_cfg)

    def _resolved_source_values(self, source_cfg: Any) -> dict[str, Any]:
        """The window the section writes, bound as datetimes.

        A source that falls back on the dates of ``[data.<name>]`` when the run
        carries no period (the SHOM tide gauges) reads them here; the keys a
        constructor does not name are dropped, so only a source that asks for
        them receives them.
        """
        del source_cfg
        config_period = self._config_period()
        if config_period is None:
            return {}
        return {"date_start": config_period[0], "date_end": config_period[1]}

    def _fetch_listed_source(self, source: Any, source_cfg: Any) -> list[FieldRecord | PointRecord]:
        cached = self._is_a_cached_download(source, source_cfg)

        # No cache folder means no side file worth keeping: a scratch owned by
        # this call is the out_dir, and goes when the call does.
        with TemporaryDirectory(prefix="hmp-fields-") as scratch:
            out_dir = self.data_dir if self.data_dir is not None else Path(scratch)

            if not source.selectors:
                # A computed source is asked exactly nothing: the loader fills
                # mask_path on every section whose model declares it, and the
                # extent it names is nobody's to read here.
                period = self.project_period
                request_period = (
                    Period(start=period[0], end=period[1]) if period is not None else None
                )
                request = FetchRequest(out_dir=out_dir, period=request_period)
                return records_of(source.fetch(request))

            if not cached:
                request = self._field_request(source_cfg, out_dir=out_dir)
                return records_of(source.fetch(request))

            def _download(cfg: Any, *, bbox, project_period) -> list[FieldRecord]:
                del bbox, cfg  # the request resolves the same box itself
                request = self._field_request(source_cfg, out_dir=out_dir, period=project_period)
                records = records_of(source.fetch(request))
                return [record for record in records if isinstance(record, FieldRecord)]

            return self._load_or_fetch_fields(
                source_cfg,
                source_cfg.source,
                _download,
                variable_names=list(source.variables),
            )

    def _is_a_cached_download(self, source: Any, source_cfg: Any) -> bool:
        """Whether this variable keys the source's grids on the box and the window.

        A source that answers fields, selects by extent and reads no named file
        is a download: its grids are cut to a box and a window, exactly what the
        grid cache keys on. Everything else is read again at each run: a file
        the user names (the download cache keys on the box and the dates, never
        on the file, and would hand back the grid of the previous file), a
        source with its own cache, and a source computed from the section.
        """
        return (
            getattr(source, "payload_kind", None) == "fields"
            and "extent" in getattr(source, "selectors", ())
            and getattr(source_cfg, "path", None) is None
        )

    def _field_request(
        self,
        source_cfg: Any,
        *,
        out_dir: Path,
        period: tuple[datetime, datetime] | None = None,
    ) -> FetchRequest:
        """The question a field source is asked: the extent as it is, and the window.

        The extent is what :func:`resolve_source_extent` resolves: the box of
        the mask in the CRS the mask is in, or the project extent in the frame
        the grid variables receive it. A source that declares no selector
        receives neither, and the same source asking through
        :func:`~hydromodpy.data.source.port.extent_for` converts it into the
        frame it declares.
        """
        if period is None:
            period = self.project_period
        request_period = Period(start=period[0], end=period[1]) if period is not None else None
        extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        return FetchRequest(out_dir=out_dir, extent=extent, period=request_period)

    # ------------------------------------------------------------------
    # Bbox resolution and spatial mask (native CRS for grid data)
    # ------------------------------------------------------------------

    def _load_mask_geometry(self, mask_path: Path):
        """Grid variables keep the mask in its native CRS."""
        from hydromodpy.data.common.source_extent import mask_geometry

        return mask_geometry(mask_path)[0]

    def _handle_file_results(self, records: list, source_cfg) -> list:
        """Dispatch file results: mask the PointRecords, keep the FieldRecords.

        A file of the user is read where it lies and is no row of the data cache.
        """
        point_records = [r for r in records if isinstance(r, PointRecord)]
        field_records = [r for r in records if isinstance(r, FieldRecord)]
        result: list = []
        if point_records:
            result.extend(self._apply_mask(point_records, source_cfg))
        result.extend(field_records)
        return result

    # ------------------------------------------------------------------
    # Grid cache: look up the rows -> load .nc or fetch API -> persist
    # ------------------------------------------------------------------

    def _load_or_fetch_fields(
        self,
        source_cfg,
        source_name: str,
        fetch_fn,
        *,
        variable_names: list[str] | None = None,
    ) -> list[FieldRecord]:
        """Reuse cached grids that cover the request, or fetch and cache them."""
        bbox = self._resolve_bbox(source_cfg)
        if variable_names is None:
            variable_names = [self.VARIABLE_NAME]

        if not source_cfg.force_refresh:
            cached = self._find_cached_fields(
                source=source_name,
                variable_names=variable_names,
                bbox=bbox,
            )
            if cached is not None:
                return cached

        records = fetch_fn(
            source_cfg,
            bbox=bbox,
            project_period=self.project_period,
        )
        self._persist_field_records(records, source_name)
        return records

    def _find_cached_fields(
        self,
        *,
        source: str,
        variable_names: list[str],
        bbox: tuple | None,
    ) -> list[FieldRecord] | None:
        """Return all cached FieldRecords iff all *variable_names* are cached."""
        if self.index is None or self.data_dir is None:
            return None

        date_start = self.project_period[0] if self.project_period else None
        date_end = self.project_period[1] if self.project_period else None

        results: list[FieldRecord] = []
        for var_name in variable_names:
            row = self.index.find(
                var_name,
                source,
                bbox=bbox,
                date_start=date_start,
                date_end=date_end,
            )
            if row is None:
                return None

            if self.index.is_stale(row):
                self.index.forget(row)
                return None
            nc_path = row.path

            import xarray as xr

            ds = xr.open_dataset(nc_path)
            if not row.crs:
                raise ValueError(
                    f"Cached field {var_name!r} from {source!r} is missing CRS metadata."
                )
            logger.debug("Cache hit: %s from %s", var_name, nc_path.name)

            results.append(
                FieldRecord(
                    variable=var_name,
                    source=source,
                    unit=row.unit or self.INTERNAL_UNIT,
                    data=ds,
                    bbox=row.bbox,
                    crs=row.crs,
                    date_start=_coerce_datetime(row.date_start),
                    date_end=_coerce_datetime(row.date_end),
                    frequency=row.frequency,
                    source_unit=self._extract_field_source_unit(ds, var_name) or row.source_unit,
                    metadata={"source_path": str(nc_path)},
                )
            )

        return results

    def _persist_field_records(
        self,
        records: list[FieldRecord],
        source: str,
    ) -> None:
        """Save FieldRecords as .nc files, write their sidecars, subsume the smaller grids."""
        if self.data_dir is None or not records:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)

        for rec in records:
            filename = self._nc_filename(
                rec.variable,
                source,
                rec.bbox,
                rec.date_start,
                rec.date_end,
            )
            nc_path = self.data_dir / filename

            if not rec.is_file_reference:
                self._write_netcdf(rec.data, nc_path)
                logger.debug("Saved: %s", nc_path.name)
            else:
                nc_path = Path(rec.data)
            # The seal records this file as the input of the run that read it.
            rec.metadata["source_path"] = str(nc_path)

            row = self._register_field(rec, nc_path, source)
            if row is None:
                continue
            rec.metadata["source_path"] = str(row.path)
            removed = self.index.subsume(row)
            if removed:
                logger.debug("Subsumed %d smaller grid(s) for %s", removed, rec.variable)

    @staticmethod
    def _write_netcdf(data: Any, path: Path) -> None:
        """Write *data* beside *path* and rename it in place, so a reader never sees half a grid."""
        part = path.with_name(f".{path.name}.{os.getpid()}.part")
        try:
            data.to_netcdf(part)
            os.replace(part, path)
        finally:
            part.unlink(missing_ok=True)

    def _register_field(
        self,
        rec: FieldRecord,
        nc_path: Path,
        source: str,
    ) -> CacheRow | None:
        """Write the sidecar of a downloaded grid and return its row.

        A file a source references from outside the data folder is no row of
        this cache, so it gets none.
        """
        if self.index is None or self.index.data_root is None:
            return None
        if not nc_path.resolve().is_relative_to(self.index.data_root):
            logger.debug("%s lies outside the data folder: not a row of the cache", nc_path)
            return None
        return self.index.record(
            nc_path,
            variable=rec.variable,
            source=source,
            bbox=rec.bbox,
            crs=rec.crs,
            date_start=rec.date_start,
            date_end=rec.date_end,
            frequency=rec.frequency,
            unit=rec.unit,
            source_unit=rec.source_unit,
        )

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


def _coerce_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return datetime.fromisoformat(str(value))
