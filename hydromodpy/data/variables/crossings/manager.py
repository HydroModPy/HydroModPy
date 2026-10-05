"""Crossings manager: download or read the structures laid across the channels.

Each source gives one file of the fixed records of
:mod:`~hydromodpy.data.variables.crossings.records`, cached as
``crossings_<source>_<bbox hash>.gpkg`` and indexed in the catalog. The sources
are not merged here: ``resolver`` merges them for the geographic step, and a
data request writes one file per source.

The box a download is asked over is the bounds of ``mask_path``, which a
project run fills in from the delineated watershed. Features come whole, so a
road that leaves the box is not cut.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import cache_dir as _hmp_cache_dir
from hydromodpy.data.common.geo_helpers import bbox_hash
from hydromodpy.data.common.source_extent import (
    PROJECT_EXTENT_CRS,
    mask_extent_in,
)
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.managers.base_manager_common import (
    CUSTOM_SOURCE,
    SourceContext,
    SourceTable,
)
from hydromodpy.data.provenance.derived import custom_derived_dir, derived_path
from hydromodpy.data.source.port import Extent
from hydromodpy.data.variables.crossings import custom, records
from hydromodpy.data.variables.crossings.apis import bdtopo, roe, wfs

logger = get_logger(__name__)

VARIABLE = "crossings"
FILE_PREFIX = f"{VARIABLE}_"
"""A downloaded file is ``crossings_<source>_<bbox hash>.gpkg``."""


class CrossingsManager(SourceTable):
    """Load the crossings of every configured source."""

    VARIABLE_NAME = VARIABLE
    SOURCES = {
        bdtopo.SOURCE_ID: bdtopo.fetch_pages,
        roe.SOURCE_ID: roe.fetch_pages,
    }

    def __init__(
        self,
        *,
        config: Any,
        catalog: Any,
        project_extent: tuple | None = None,
        project_period: tuple | None = None,
        data_dir: Path | None = None,
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.project_period = project_period
        self.data_dir = Path(data_dir) if data_dir else None

    def load(self) -> LoadResult:
        """One field record per source, each pointing to a file of records."""
        result = LoadResult()
        for source_cfg in self.config.sources:
            result.fields.extend(self._fetch_from_source(source_cfg))
        return result

    # ------------------------------------------------------------------
    # Custom
    # ------------------------------------------------------------------

    def load_custom(self, source_cfg: Any) -> list[FieldRecord]:
        """Normalise the user's file into a GeoParquet copy and index it."""
        frame = custom.load_custom(source_cfg)
        origin = custom.vector_file(source_cfg.path).resolve()
        stat = origin.stat()
        derived_dir = custom_derived_dir(self.data_dir, VARIABLE) or (
            Path(_hmp_cache_dir()) / VARIABLE / "custom"
        )
        derived_dir.mkdir(parents=True, exist_ok=True)
        out_path = derived_path(
            derived_dir,
            origin,
            kind="records",
            suffix=".parquet",
            inputs=(str(stat.st_mtime_ns), str(stat.st_size)),
        )
        with staged_path(out_path) as staged:
            frame.to_parquet(staged)
        bbox = tuple(float(value) for value in frame.total_bounds)
        crs = str(frame.crs)
        if self.catalog is not None:
            self.catalog.register(
                variable=VARIABLE,
                source=CUSTOM_SOURCE,
                file_path=str(out_path),
                bbox=bbox,
                crs=crs,
                is_custom=True,
            )
        return [self._record("custom", out_path, bbox, crs)]

    # ------------------------------------------------------------------
    # Downloads
    # ------------------------------------------------------------------

    def _fetch_listed_source(self, fetch: Callable[..., Any], source_cfg: Any) -> list[FieldRecord]:
        """Ask the provider for the box, or reuse the file the catalog holds.

        *fetch* hands out the records page by page, and each page is written as it
        arrives.
        """
        name = str(source_cfg.source)
        bbox = self._request_bbox()
        if not source_cfg.force_refresh:
            cached = self._cached(name, bbox)
            if cached is not None:
                return [self._record(name, cached, bbox, wfs.QUERY_CRS)]

        out_dir = self.data_dir or Path(_hmp_cache_dir()) / VARIABLE
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / cache_file_name(name, bbox)
        started = time.perf_counter()
        with staged_path(out_path) as staged:
            count = records.append_pages(
                staged, fetch(source_cfg, bbox=bbox, context=self._context()), wfs.QUERY_CRS
            )
            if count == 0:
                records.empty(wfs.QUERY_CRS).to_file(staged, driver="GPKG")
        logger.info(
            "Crossings from %s: %d features in %s, %.1f s",
            name,
            count,
            out_path,
            time.perf_counter() - started,
        )
        self._register(name, out_path, bbox)
        return [self._record(name, out_path, bbox, wfs.QUERY_CRS)]

    def _request_bbox(self) -> tuple[float, float, float, float]:
        """The box the providers are asked over, in the CRS they answer in."""
        mask_path = getattr(self.config, "mask_path", None)
        if mask_path:
            return mask_extent_in(mask_path, wfs.QUERY_CRS).bbox
        if self.project_extent:
            xmin, ymin, xmax, ymax = self.project_extent
            extent = Extent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs=PROJECT_EXTENT_CRS)
            return extent.to_crs(wfs.QUERY_CRS).bbox
        raise DataRequestError(
            "[data.crossings] downloads over a box, and none is given: set "
            "data.crossings.mask_path, or run it inside a project."
        )

    def _context(self) -> SourceContext:
        return SourceContext(
            project_extent=self.project_extent,
            data_dir=self.data_dir,
            config_period=None,
        )

    def _cached(self, source: str, bbox: tuple[float, float, float, float]) -> Path | None:
        if self.catalog is None:
            return None
        entry = self.catalog.find_cached(variable=VARIABLE, source=source, bbox=bbox)
        if entry is None:
            return None
        path = self.catalog.resolve_path(entry.file_path, variable=VARIABLE)
        return path if path.exists() else None

    def _register(self, source: str, path: Path, bbox: tuple[float, float, float, float]) -> None:
        if self.catalog is None:
            return
        entry_id = self.catalog.register(
            variable=VARIABLE,
            source=source,
            file_path=str(path),
            bbox=bbox,
            crs=wfs.QUERY_CRS,
            is_custom=False,
        )
        self.catalog.subsume_entries(
            variable=VARIABLE,
            source=source,
            bbox=bbox,
            date_start=None,
            date_end=None,
            exclude_id=entry_id,
        )

    @staticmethod
    def _record(source: str, path: Path, bbox: tuple, crs: str) -> FieldRecord:
        return FieldRecord(
            variable=VARIABLE, source=source, unit="-", data=path, bbox=bbox, crs=crs
        )


def cache_file_name(source: str, bbox: tuple[float, float, float, float]) -> str:
    """``crossings_<source>_<bbox hash>.gpkg``, the name of a downloaded file."""
    return f"{FILE_PREFIX}{source}_{bbox_hash(bbox)}.gpkg"
