"""DEM variable manager — standard data-manager pattern.

Downloads, caches, and serves DEM data from IGN BD ALTI or custom
files. Returns a ``LoadResult`` containing ``FieldRecord`` objects
pointing to cached GeoTIFF files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data_managers.common.geo_helpers import bbox_hash as _bbox_hash
from hydromodpy.data_managers.contracts.load_result import LoadResult
from hydromodpy.data_managers.contracts.spatial_field import FieldRecord


class DemManager:
    """Orchestrator for DEM data acquisition and caching.

    Follows the standard variable-manager pattern:
    - iterates over configured sources,
    - checks catalog cache (bbox-based, no temporal dimension),
    - downloads / loads on miss,
    - registers in SQL catalog with subsumption.
    """

    VARIABLE_NAME = "dem"

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
        """Load DEM data from all configured sources."""
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
        if source_cfg.source == "ign_bdalti":
            return self._fetch_ign_bdalti(source_cfg)
        elif source_cfg.source == "custom":
            return self._fetch_custom(source_cfg)
        else:
            raise ValueError(f"Unknown DEM source: {source_cfg.source}")

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
        """Resolve bbox and reproject to EPSG:2154 (IGN BD ALTI CRS)."""
        bbox = self._resolve_bbox(source_cfg)
        if bbox is None:
            return None
        # BD ALTI data is in EPSG:2154 — reproject bbox if needed.
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
    # IGN BD ALTI 25 m
    # ------------------------------------------------------------------

    def _fetch_ign_bdalti(self, source_cfg) -> list[FieldRecord]:
        """Fetch BD ALTI 25 m MNT from IGN GéoPlateforme."""
        bbox = self._resolve_bbox_2154(source_cfg)
        if bbox is None:
            raise ValueError(
                "ign_bdalti source requires a bbox "
                "(set mask_path, extent, or geographic)"
            )
        force_refresh = getattr(source_cfg, "force_refresh", False)

        # Check cache
        if not force_refresh and self.catalog is not None:
            cached = self.catalog.find_cached(
                variable="dem", source="ign_bdalti", bbox=bbox,
            )
            if cached is not None and cached.file_path not in ("custom", "empty"):
                cached_path = Path(cached.file_path)
                if cached_path.exists():
                    return [FieldRecord(
                        variable="dem", source="ign_bdalti",
                        unit="m", data=cached_path,
                        bbox=bbox, crs="EPSG:2154",
                    )]

        from hydromodpy.data_managers.variables.dem.apis.ign_bdalti import fetch_bdalti

        output_dir = self.data_dir or Path.home() / ".cache" / "hydromodpy" / "dem"
        tif_path = fetch_bdalti(
            output_dir=output_dir,
            bbox=bbox,
        )

        record = FieldRecord(
            variable="dem", source="ign_bdalti",
            unit="m", data=tif_path,
            bbox=bbox, crs="EPSG:2154",
        )

        # Register in catalog
        if self.catalog is not None:
            entry_id = self.catalog.register(
                variable="dem", source="ign_bdalti",
                file_path=str(tif_path), bbox=bbox, crs="EPSG:2154",
            )
            self.catalog.subsume_entries(
                variable="dem", source="ign_bdalti",
                bbox=bbox, date_start=None, date_end=None,
                exclude_id=entry_id,
            )

        return [record]

    # ------------------------------------------------------------------
    # Custom
    # ------------------------------------------------------------------

    def _fetch_custom(self, source_cfg) -> list[FieldRecord]:
        """Load custom DEM data (TIF, ASC, NC)."""
        from hydromodpy.data_managers.variables.dem.custom import load_custom_dem

        bbox = self._resolve_bbox(source_cfg)

        records = load_custom_dem(
            source_cfg,
            bbox=bbox,
            data_dir=self.data_dir,
        )

        # Register custom entries (never subsumed)
        if self.catalog is not None:
            for rec in records:
                if isinstance(rec, FieldRecord) and isinstance(rec.data, Path):
                    self.catalog.register(
                        variable="dem", source="custom",
                        file_path=str(rec.data),
                        bbox=rec.bbox, crs=rec.crs, is_custom=True,
                    )

        return records
