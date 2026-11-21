"""Load the sealed share: the user's raster, a url, or a provider asked over the watershed."""

from __future__ import annotations

from typing import Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.data.common.source_extent import resolve_source_extent
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.families.files import RasterFileVariable
from hydromodpy.data.source.port import FetchRequest


class ImperviousVariable(RasterFileVariable):
    """The sealed share, one raster 0 to 1 per pixel."""

    VARIABLE_NAME = "impervious"
    INTERNAL_UNIT = "-"

    def _fetch_listed_source(self, source: Any, source_cfg: Any) -> list[FieldRecord]:
        """Ask the provider over the mask the loader fills with the watershed."""
        name = str(source_cfg.source)
        extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        if extent is None:
            raise ConfigError(
                f'[data.impervious] source = "{name}" is asked over the watershed, and none '
                "is known: run it from a project, or set mask_path."
            )
        if self.data_dir is None:
            raise ConfigError(
                f'[data.impervious] source = "{name}" builds a map and has no data folder to '
                "put it in. Run it from a workspace or a project."
            )
        result = source.fetch(FetchRequest(out_dir=self.data_dir, extent=extent))
        path = result.files[0].path
        crs = result.extent.crs
        bbox = result.extent.bbox
        if self.index is not None:
            self.index.record(path, variable=self.VARIABLE_NAME, source=name, bbox=bbox, crs=crs)
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


__all__ = ["ImperviousVariable"]
