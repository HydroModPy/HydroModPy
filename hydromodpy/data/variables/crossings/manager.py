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

from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.state.portable import cache_dir as _hmp_cache_dir
from hydromodpy.data.common.source_extent import (
    PROJECT_EXTENT_CRS,
    mask_extent_in,
)
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.managers.base_manager_common import CUSTOM_SOURCE, SourceTable
from hydromodpy.data.provenance.derived import custom_derived_dir, derived_path
from hydromodpy.data.source.port import Extent, FetchRequest
from hydromodpy.data.variables.crossings import custom
from hydromodpy.data.variables.crossings.apis import wfs

VARIABLE = "crossings"
FILE_PREFIX = f"{VARIABLE}_"
"""A downloaded file is ``crossings_<source>_<bbox hash>.gpkg``."""


class CrossingsManager(SourceTable):
    """Load the crossings of every configured source.

    A downloading source is a class of the ``data_sources`` registry under the
    ``crossings`` section. The manager owns the catalog: on a hit it serves the
    cached file without asking the provider, and on a miss it hands the source
    its data folder and wraps the file it returns into the ``FieldRecord`` the
    loader reads.
    """

    VARIABLE_NAME = VARIABLE

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
    # Registered sources
    # ------------------------------------------------------------------

    def _fetch_listed_source(self, source: Any, source_cfg: Any) -> list[FieldRecord]:
        """Ask the provider for the box, or reuse the file the catalog holds."""
        name = str(getattr(source_cfg, "source", "")).strip()
        extent = self._request_extent()
        if not getattr(source_cfg, "force_refresh", False):
            cached = self._cached(name, extent.bbox)
            if cached is not None:
                return [self._record(name, cached, extent.bbox, wfs.QUERY_CRS)]

        out_dir = self.data_dir or Path(_hmp_cache_dir()) / VARIABLE
        result = source.fetch(FetchRequest(out_dir=Path(out_dir), extent=extent))

        fields = [
            self._record(name, file_record.path, extent.bbox, wfs.QUERY_CRS)
            for file_record in result.files
        ]
        for field in fields:
            self._register(name, Path(field.data), extent.bbox)
        return fields

    def _request_extent(self) -> Extent:
        """The extent the providers are asked over, in the CRS they answer in."""
        mask_path = getattr(self.config, "mask_path", None)
        if mask_path:
            return mask_extent_in(mask_path, wfs.QUERY_CRS)
        if self.project_extent:
            xmin, ymin, xmax, ymax = self.project_extent
            extent = Extent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs=PROJECT_EXTENT_CRS)
            return extent.to_crs(wfs.QUERY_CRS)
        raise DataRequestError(
            "[data.crossings] downloads over a box, and none is given: set "
            "data.crossings.mask_path, or run it inside a project."
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

    # ------------------------------------------------------------------
    # Custom
    # ------------------------------------------------------------------

    def load_custom(self, source_cfg: Any) -> list[FieldRecord]:
        """Normalize the user's file into a GeoParquet copy and index it."""
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


def cache_file_name(source: str, bbox: tuple[float, float, float, float]) -> str:
    """``crossings_<source>_<bbox hash>.gpkg``, the name of a downloaded file."""
    from hydromodpy.data.common.geo_helpers import bbox_hash

    return f"{FILE_PREFIX}{source}_{bbox_hash(bbox)}.gpkg"
