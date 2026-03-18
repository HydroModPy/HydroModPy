"""Geology variable manager — standard data-manager pattern.

Downloads, caches, and serves geology data from BRGM APIs or custom
files. Returns a ``LoadResult`` containing ``FieldRecord`` objects
pointing to cached GeoPackage/GeoTIFF files.

The ``GeologyField`` (field framework) is NOT built here — that
happens in the runtime_loader, which takes the loaded geodata and
rasterizes it on the domain grid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data_managers.common.geo_helpers import bbox_hash as _bbox_hash
from hydromodpy.data_managers.contracts.load_result import LoadResult
from hydromodpy.data_managers.contracts.spatial_field import FieldRecord


class GeologyManager:
    """Orchestrator for geology data acquisition and caching.

    Follows the standard variable-manager pattern:
    - iterates over configured sources,
    - checks catalog cache (bbox-based, no temporal dimension),
    - downloads / loads on miss,
    - registers in SQL catalog with subsumption.
    """

    VARIABLE_NAME = "geology"

    def __init__(
        self,
        *,
        config: Any,
        catalog: Any,
        project_extent: tuple | None = None,
        data_dir: Path | None = None,
        geographic: Any = None,
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.data_dir = Path(data_dir) if data_dir else None
        self.geographic = geographic

    def load(self) -> LoadResult:
        """Load geology data from all configured sources."""
        result = LoadResult()
        for source_cfg in self.config.sources:
            records = self._fetch_from_source(source_cfg)
            if not isinstance(records, list):
                records = [records]
            for rec in records:
                if isinstance(rec, FieldRecord):
                    result.fields.append(rec)
                elif rec is not None:
                    result.points.append(rec)
        return result

    def _fetch_from_source(self, source_cfg) -> list:
        """Dispatch to the right loader based on source type."""
        if source_cfg.source == "brgm_1m":
            return self._fetch_brgm_1m(source_cfg)
        elif source_cfg.source == "brgm_50k":
            return self._fetch_brgm_50k(source_cfg)
        elif source_cfg.source == "custom":
            return self._fetch_custom(source_cfg)
        else:
            raise ValueError(f"Unknown geology source: {source_cfg.source}")

    # ------------------------------------------------------------------
    # Bbox resolution
    # ------------------------------------------------------------------

    def _resolve_bbox(self, source_cfg) -> tuple | None:
        """Resolve bounding box from mask, extent, or geographic."""
        if getattr(source_cfg, "mask_path", None):
            from hydromodpy.data_managers.common.geo_helpers import (
                geometry_to_bbox,
                load_mask_geometry,
            )
            geom = load_mask_geometry(source_cfg.mask_path)
            return geometry_to_bbox(geom)
        if getattr(source_cfg, "extent", None) and self.project_extent:
            return self.project_extent
        if self.geographic is not None:
            watershed_shp = getattr(self.geographic, "watershed_shp", None)
            if watershed_shp:
                from hydromodpy.data_managers.common.geo_helpers import (
                    geometry_to_bbox,
                    load_mask_geometry,
                )
                geom = load_mask_geometry(watershed_shp)
                return geometry_to_bbox(geom)
        return None

    def _resolve_bbox_2154(self, source_cfg) -> tuple | None:
        """Resolve bbox and reproject to EPSG:2154 (BRGM data CRS)."""
        bbox = self._resolve_bbox(source_cfg)
        if bbox is None:
            return None
        # BRGM data is in EPSG:2154 — reproject bbox if needed
        if self.geographic is not None:
            watershed_shp = getattr(self.geographic, "watershed_shp", None)
            if watershed_shp:
                import geopandas as gpd
                from shapely.geometry import box
                gdf = gpd.GeoDataFrame(
                    geometry=[box(*bbox)],
                    crs=gpd.read_file(str(watershed_shp), rows=0).crs,
                )
                gdf_2154 = gdf.to_crs("EPSG:2154")
                bounds = gdf_2154.total_bounds
                return tuple(bounds)
        return bbox

    # ------------------------------------------------------------------
    # BRGM 1:1M
    # ------------------------------------------------------------------

    # BRGM data always uses this attribute column.
    _BRGM_CODE_FIELD = "CODE_LEG"

    def _fetch_brgm_1m(self, source_cfg) -> list[FieldRecord]:
        """Fetch the 1:1M national geological map from BRGM."""
        bbox = self._resolve_bbox_2154(source_cfg)
        code_field = self._BRGM_CODE_FIELD
        force_refresh = getattr(source_cfg, "force_refresh", False)

        # Check cache
        if not force_refresh and self.catalog is not None and bbox is not None:
            cached = self.catalog.find_cached(
                variable="geology", source="brgm_1m", bbox=bbox,
            )
            if cached is not None and cached.file_path not in ("custom", "empty"):
                cached_path = Path(cached.file_path)
                if cached_path.exists():
                    return [FieldRecord(
                        variable="geology", source="brgm_1m",
                        unit="category", data=cached_path,
                        bbox=bbox, crs="EPSG:2154",
                    )]

        from hydromodpy.data_managers.variables.geology.apis.brgm_1m import fetch_brgm_1m

        output_dir = self.data_dir or Path.home() / ".cache" / "hydromodpy" / "geology"
        gpkg_path = fetch_brgm_1m(
            output_dir=output_dir,
            bbox=bbox,
            code_field=code_field,
        )

        record = FieldRecord(
            variable="geology", source="brgm_1m",
            unit="category", data=gpkg_path,
            bbox=bbox, crs="EPSG:2154",
        )

        # Register in catalog
        if self.catalog is not None and bbox is not None:
            entry_id = self.catalog.register(
                variable="geology", source="brgm_1m",
                file_path=str(gpkg_path), bbox=bbox, crs="EPSG:2154",
            )
            self.catalog.subsume_entries(
                variable="geology", source="brgm_1m",
                bbox=bbox, date_start=None, date_end=None,
                exclude_id=entry_id,
            )

        return [record]

    # ------------------------------------------------------------------
    # BRGM 1:50K
    # ------------------------------------------------------------------

    def _fetch_brgm_50k(self, source_cfg) -> list[FieldRecord]:
        """Fetch 1:50K departmental geological maps from BRGM."""
        bbox = self._resolve_bbox_2154(source_cfg)
        if bbox is None:
            raise ValueError(
                "brgm_50k source requires a bbox (set mask_path, extent, or geographic)"
            )
        code_field = self._BRGM_CODE_FIELD
        force_refresh = getattr(source_cfg, "force_refresh", False)

        # Check cache
        if not force_refresh and self.catalog is not None:
            cached = self.catalog.find_cached(
                variable="geology", source="brgm_50k", bbox=bbox,
            )
            if cached is not None and cached.file_path not in ("custom", "empty"):
                cached_path = Path(cached.file_path)
                if cached_path.exists():
                    return [FieldRecord(
                        variable="geology", source="brgm_50k",
                        unit="category", data=cached_path,
                        bbox=bbox, crs="EPSG:2154",
                    )]

        from hydromodpy.data_managers.variables.geology.apis.brgm_50k import fetch_brgm_50k

        output_dir = self.data_dir or Path.home() / ".cache" / "hydromodpy" / "geology"
        gpkg_path = fetch_brgm_50k(
            output_dir=output_dir,
            bbox=bbox,
            code_field=code_field,
        )

        record = FieldRecord(
            variable="geology", source="brgm_50k",
            unit="category", data=gpkg_path,
            bbox=bbox, crs="EPSG:2154",
        )

        if self.catalog is not None:
            entry_id = self.catalog.register(
                variable="geology", source="brgm_50k",
                file_path=str(gpkg_path), bbox=bbox, crs="EPSG:2154",
            )
            self.catalog.subsume_entries(
                variable="geology", source="brgm_50k",
                bbox=bbox, date_start=None, date_end=None,
                exclude_id=entry_id,
            )

        return [record]

    # ------------------------------------------------------------------
    # Custom
    # ------------------------------------------------------------------

    def _fetch_custom(self, source_cfg) -> list[FieldRecord]:
        """Load custom geology data (SHP, GPKG, TIF, CSV)."""
        from hydromodpy.data_managers.variables.geology.custom import load_custom_geology

        bbox = self._resolve_bbox(source_cfg)
        code_field = getattr(source_cfg, "code_field", None)

        records = load_custom_geology(
            source_cfg,
            code_field=code_field,
            bbox=bbox,
            data_dir=self.data_dir,
        )

        # Register custom entries (never subsumed)
        if self.catalog is not None:
            for rec in records:
                if isinstance(rec, FieldRecord) and isinstance(rec.data, Path):
                    self.catalog.register(
                        variable="geology", source="custom",
                        file_path=str(rec.data),
                        bbox=rec.bbox, crs=rec.crs, is_custom=True,
                    )

        return records
