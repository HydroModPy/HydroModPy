"""Lake-bathymetry manager: lake-bed elevation rasters from the user's files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.managers.base_manager_file import BaseFileManager


class LakeBathymetryManager(BaseFileManager):
    VARIABLE_NAME = "lake_bathymetry"
    RECORD_KIND = "fields"

    def read_custom(self, source_cfg: Any, *, derived_dir: Path | None) -> list[FieldRecord]:
        """Read a GeoTIFF or ASC raster into a cached COG."""
        from hydromodpy.data.variables.lake_bathymetry.custom import (
            load_custom_lake_bathymetry,
        )

        return load_custom_lake_bathymetry(source_cfg, derived_dir=derived_dir)
