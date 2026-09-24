"""Lake-bathymetry variable manager - hand-written field-manager pattern.

Loads and caches lake-bed elevation rasters from custom files. Returns a
``LoadResult`` containing ``FieldRecord`` objects pointing to cached COG
GeoTIFF files (mirror of :class:`GeologyManager`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.managers.base_manager_common import SourceTable
from hydromodpy.data.provenance.derived import custom_derived_dir


class LakeBathymetryManager(SourceTable):
    """Orchestrator for lake-bathymetry data acquisition and caching."""

    VARIABLE_NAME = "lake_bathymetry"

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
        """Load lake-bathymetry data from all configured sources."""
        result = LoadResult()
        for source_cfg in self.config.sources:
            for rec in self._fetch_from_source(source_cfg):
                result.fields.append(rec)
        return result

    def load_custom(self, source_cfg) -> list[FieldRecord]:
        """Load custom lake-bathymetry data (GeoTIFF, ASC)."""
        from hydromodpy.data.variables.lake_bathymetry.custom import (
            load_custom_lake_bathymetry,
        )

        records = load_custom_lake_bathymetry(
            source_cfg, derived_dir=custom_derived_dir(self.data_dir, self.VARIABLE_NAME)
        )

        if self.catalog is not None:
            for rec in records:
                if isinstance(rec.data, Path):
                    self.catalog.register(
                        variable="lake_bathymetry",
                        source="custom",
                        file_path=str(rec.data),
                        bbox=rec.bbox,
                        crs=rec.crs,
                        is_custom=True,
                    )

        return records
