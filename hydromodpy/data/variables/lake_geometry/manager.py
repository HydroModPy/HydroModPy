"""Lake-geometry manager: lake and reservoir footprints from the user's files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.managers.base_manager_file import BaseFileManager


class LakeGeometryManager(BaseFileManager):
    VARIABLE_NAME = "lake_geometry"
    RECORD_KIND = "fields"

    def read_custom(self, source_cfg: Any, *, derived_dir: Path | None) -> list[FieldRecord]:
        """Read a SHP, GPKG or GeoJSON footprint into a cached GeoParquet."""
        from hydromodpy.data.variables.lake_geometry.custom import load_custom_lake_geometry

        return load_custom_lake_geometry(source_cfg, derived_dir=derived_dir)
