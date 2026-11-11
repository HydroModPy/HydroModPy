"""Crossings variable: download or read the structures laid across the channels.

Each source gives one file of the fixed records of
:mod:`~hydromodpy.data.variables.crossings.records`, cached as
``crossings_<source>_<bbox hash>.gpkg`` with its sidecar. The sources
are not merged here: ``resolver`` merges them for the geographic step, and a
data request writes one file per source.

The box a download is asked over is the bounds of ``mask_path``, which a
project run fills in from the delineated watershed. Features come whole, so a
road that leaves the box is not cut. A download, and the copy made from a file
of the user, need the data folder of the call and are refused without one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigError, DataRequestError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.data.common.source_extent import (
    PROJECT_EXTENT_CRS,
    mask_extent_in,
)
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.families.common import SourceTable
from hydromodpy.data.provenance import derived
from hydromodpy.data.provenance.derived import derived_path
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.source.port import Extent, FetchRequest
from hydromodpy.data.variables.crossings import custom
from hydromodpy.data.variables.crossings.apis import wfs

VARIABLE = "crossings"
FILE_PREFIX = f"{VARIABLE}_"
"""A downloaded file is ``crossings_<source>_<bbox hash>.gpkg``."""


class CrossingsVariable(SourceTable):
    """Load the crossings of every configured source.

    A downloading source is a class of the ``data_sources`` registry under the
    ``crossings`` section. The variable owns the cache: on a hit it serves the
    cached file without asking the provider, and on a miss it hands the source
    its data folder, writes the sidecar of the file it returns and wraps that
    file into the ``FieldRecord`` the loader reads.
    """

    VARIABLE_NAME = VARIABLE

    def __init__(
        self,
        *,
        config: Any,
        index: CacheIndex | None,
        project_extent: tuple | None = None,
        project_period: tuple | None = None,
        data_dir: Path | None = None,
    ):
        self.config = config
        self.index = index
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
        """Ask the provider for the box, or reuse the file the cache holds."""
        name = str(getattr(source_cfg, "source", "")).strip()
        extent = self._request_extent()
        if not getattr(source_cfg, "force_refresh", False):
            cached = self._cached(name, extent.bbox)
            if cached is not None:
                return [self._record(name, cached, extent.bbox, wfs.QUERY_CRS)]

        if self.data_dir is None:
            raise ConfigError(
                f"[data.crossings] source {name!r} downloads the crossings and has no data "
                "folder to put them in. Run it from a workspace or a project, whose data/ "
                "folder holds the cache."
            )
        result = source.fetch(FetchRequest(out_dir=self.data_dir, extent=extent))

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
        if self.index is None:
            return None
        row = self.index.find(VARIABLE, source, bbox=bbox)
        if row is None or self.index.is_stale(row):
            return None
        return row.path

    def _register(self, source: str, path: Path, bbox: tuple[float, float, float, float]) -> None:
        if self.index is None:
            return
        row = self.index.record(
            path, variable=VARIABLE, source=source, bbox=bbox, crs=wfs.QUERY_CRS
        )
        self.index.subsume(row)

    @staticmethod
    def _record(source: str, path: Path, bbox: tuple, crs: str) -> FieldRecord:
        return FieldRecord(
            variable=VARIABLE, source=source, unit="-", data=path, bbox=bbox, crs=crs
        )

    # ------------------------------------------------------------------
    # The user's own file
    # ------------------------------------------------------------------

    def load_file(self, source_cfg: Any) -> list[FieldRecord]:
        """Normalize the user's file into a GeoParquet copy under ``blobs/``.

        The user's file is read where it lies and is no row of the cache. The
        copy is a derived file, and its folder is never scanned as rows.
        """
        folder = derived.derived_dir(self.data_dir, VARIABLE)
        if folder is None:
            raise ConfigError(
                "[data.crossings] normalizes a file of the user into a copy and has no data "
                "folder to put it in. Run it from a workspace or a project, whose data/ "
                "folder holds the copy."
            )
        frame = custom.load_file(source_cfg)
        origin = custom.vector_file(source_cfg.path).resolve()
        stat = origin.stat()
        folder.mkdir(parents=True, exist_ok=True)
        out_path = derived_path(
            folder,
            origin,
            kind="records",
            suffix=".parquet",
            inputs=(str(stat.st_mtime_ns), str(stat.st_size)),
        )
        with staged_path(out_path) as staged:
            frame.to_parquet(staged)
        bbox = tuple(float(value) for value in frame.total_bounds)
        return [self._record("file", out_path, bbox, str(frame.crs))]


def cache_file_name(source: str, bbox: tuple[float, float, float, float]) -> str:
    """``crossings_<source>_<bbox hash>.gpkg``, the name of a downloaded file."""
    from hydromodpy.data.common.geometry import bbox_hash

    return f"{FILE_PREFIX}{source}_{bbox_hash(bbox)}.gpkg"
