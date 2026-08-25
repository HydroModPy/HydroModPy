"""Lake-geometry variable manager - hand-written field-manager pattern.

Loads and caches lake/reservoir footprint vector data from custom files.
Returns a ``LoadResult`` containing ``FieldRecord`` objects pointing to
cached GeoParquet files (mirror of :class:`GeologyManager`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord


class LakeGeometryManager:
    """Orchestrator for lake-geometry data acquisition and caching."""

    VARIABLE_NAME = "lake_geometry"

    def __init__(
        self,
        *,
        config: Any,
        catalog: Any,
        project_extent: tuple | None = None,
        project_period: tuple | None = None,
        data_dir: Path | None = None,
        geographic: Any = None,
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.project_period = project_period
        self.data_dir = Path(data_dir) if data_dir else None
        self.geographic = geographic

    def load(self) -> LoadResult:
        """Load lake-geometry data from all configured sources."""
        result = LoadResult()
        for source_cfg in self.config.sources:
            for rec in self._fetch_from_source(source_cfg):
                result.fields.append(rec)
        return result

    def _fetch_from_source(self, source_cfg) -> list[FieldRecord]:
        """Dispatch to the right loader based on source type."""
        if source_cfg.source == "custom":
            return self._fetch_custom(source_cfg)
        raise ValueError(f"Unknown lake_geometry source: {source_cfg.source}")

    def _fetch_custom(self, source_cfg) -> list[FieldRecord]:
        """Load custom lake-geometry data (SHP, GPKG, GeoJSON)."""
        from hydromodpy.data.variables.lake_geometry.custom import (
            load_custom_lake_geometry,
        )

        records = load_custom_lake_geometry(source_cfg, data_dir=self.data_dir)

        if self.catalog is not None:
            for rec in records:
                if isinstance(rec.data, Path):
                    self.catalog.register(
                        variable="lake_geometry",
                        source="custom",
                        file_path=str(rec.data),
                        bbox=rec.bbox,
                        crs=rec.crs,
                        is_custom=True,
                    )

        return records
