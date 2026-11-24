"""Variables read only from the user's own files.

A lake abacus, a lake bathymetry and a lake footprint have no provider: each
is a file the user supplies, read where it lies. A copy the converter writes
(a clip, a format conversion) goes under ``data/blobs/<variable>/file/``, which
the cache never reads as rows. What differs between the three is the converter
and the kind of record it returns; this base holds the rest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.geometry import crs_of_a_user_file
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.families.common import SourceTable
from hydromodpy.data.provenance import derived
from hydromodpy.data.provenance.derived import derived_path
from hydromodpy.data.provenance.sidecars import CacheIndex

logger = get_logger(__name__)


class FileVariable(SourceTable):
    """Load user files through ``read_file_source``."""

    RECORD_KIND: ClassVar[Literal["tables", "fields"]] = "fields"
    """The member of :class:`LoadResult` the records land in."""

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
        """Load every configured source."""
        result = LoadResult()
        for source_cfg in self.config.sources:
            getattr(result, self.RECORD_KIND).extend(self._fetch_from_source(source_cfg))
        return result

    def load_file(self, source_cfg: Any) -> list[Any]:
        """Convert the user's file. The file is no row of the data cache."""
        return self.read_file_source(
            source_cfg, derived_dir=derived.derived_dir(self.data_dir, self.VARIABLE_NAME)
        )

    def read_file_source(self, source_cfg: Any, *, derived_dir: Path | None) -> list[Any]:
        """Read one source config into records; each variable names its converter."""
        raise NotImplementedError


class RasterFileVariable(FileVariable):
    """Load a user's single-band raster (GeoTIFF/ASC) into a cached COG.

    Shared by every raster-only variable read from the user's own files
    (``lake_bathymetry``, ``substratum``): each subclass sets only
    ``VARIABLE_NAME``.
    """

    RECORD_KIND = "fields"
    INTERNAL_UNIT = "m"

    def read_file_source(self, source_cfg: Any, *, derived_dir: Path | None) -> list[FieldRecord]:
        """Read a GeoTIFF or ASC raster into a cached COG."""
        import rasterio

        from hydromodpy.data.ingest.raster import convert_asc_to_geotiff

        path = Path(str(source_cfg.path)).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File {self.VARIABLE_NAME} path not found: {path}")

        with rasterio.open(str(path)) as src:
            bounds = src.bounds
            has_crs = bool(src.crs)
            crs = crs_of_a_user_file(src.crs, source_cfg, path=path, variable=self.VARIABLE_NAME)
            bbox = (bounds.left, bounds.bottom, bounds.right, bounds.top)

        if derived_dir is not None:
            output_path = derived_path(derived_dir, path, kind="cog", suffix=".tif")
            convert_asc_to_geotiff(path, output_path, crs=None if has_crs else crs)
            data: Path = output_path
        else:
            data = path

        return [
            FieldRecord(
                variable=self.VARIABLE_NAME,
                source="file",
                unit=self.INTERNAL_UNIT,
                data=data,
                bbox=bbox,
                crs=crs,
            )
        ]


class ProviderRasterVariable(RasterFileVariable):
    """A raster read from the user's file, or built by a provider over the watershed.

    The sealed share and the infiltration ratio are both asked of a provider (OCS GE,
    WorldCover) over the mask the loader fills with the watershed; each subclass sets
    only ``VARIABLE_NAME`` and ``INTERNAL_UNIT``.
    """

    def _fetch_listed_source(self, source: Any, source_cfg: Any) -> list[FieldRecord]:
        """Ask the provider over the mask the loader fills with the watershed."""
        from hydromodpy.core.exceptions import ConfigError
        from hydromodpy.data.common.source_extent import resolve_source_extent
        from hydromodpy.data.source.port import FetchRequest

        name = str(source_cfg.source)
        extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        if extent is None:
            raise ConfigError(
                f'[data.{self.VARIABLE_NAME}] source = "{name}" is asked over the watershed, '
                "and none is known: run it from a project, or set mask_path."
            )
        if self.data_dir is None:
            raise ConfigError(
                f'[data.{self.VARIABLE_NAME}] source = "{name}" builds a map and has no data '
                "folder to put it in. Run it from a workspace or a project."
            )
        result = source.fetch(FetchRequest(out_dir=self.data_dir, extent=extent))
        path = result.files[0].path
        crs = result.extent.crs
        bbox = result.extent.bbox
        version = result.metadata.get("product_version")
        if self.index is not None:
            self.index.record(
                path,
                variable=self.VARIABLE_NAME,
                source=name,
                product_version=None if version is None else str(version),
                bbox=bbox,
                crs=crs,
            )
        return [
            FieldRecord(
                variable=self.VARIABLE_NAME,
                source=name,
                unit=self.INTERNAL_UNIT,
                data=path,
                bbox=bbox,
                crs=crs,
            )
        ]


__all__ = ["FileVariable", "ProviderRasterVariable", "RasterFileVariable"]
