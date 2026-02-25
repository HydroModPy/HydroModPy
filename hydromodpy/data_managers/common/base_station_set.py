"""Common station-set helpers shared by data managers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .utils import safe_file_token


class BaseStationSet:
    """Reusable utilities for station-set containers.

    This class isolates non-domain-specific logic:
    - optional geo/raster dependency loading,
    - vector/raster mask normalization into EPSG:4326 geometries,
    - normalized loader-result assignment,
    - standardized load summaries,
    - file-token normalization.
    """

    def _load_geographic_libraries(self):
        """Import optional vector-geometry dependencies on demand."""
        try:
            import geopandas as gpd
            from shapely.geometry import Point

            return gpd, Point
        except ImportError as exc:
            raise ImportError(
                "Geographic functionality requires geopandas and shapely. Install with: pip install geopandas"
            ) from exc

    def _load_raster_libraries(self):
        """Import optional raster dependencies on demand."""
        try:
            import rasterio
            from rasterio.features import shapes
            from shapely.geometry import shape

            return rasterio, shapes, shape
        except ImportError as exc:
            raise ImportError("Raster functionality requires rasterio. Install with: pip install rasterio") from exc

    @staticmethod
    def _is_raster_file(file_path):
        """Return ``True`` when the mask path looks like a raster dataset."""
        raster_extensions = {".tif", ".tiff", ".img", ".nc", ".grd", ".asc", ".bil", ".hdr"}
        return Path(file_path).suffix.lower() in raster_extensions

    def _load_mask_geometry(self, mask_path):
        """Load mask geometry from vector or raster path in EPSG:4326."""
        if self._is_raster_file(mask_path):
            return self._load_mask_from_raster(mask_path)
        return self._load_mask_from_vector(mask_path)

    def _load_mask_from_vector(self, mask_path):
        """Read a vector mask and reproject it to WGS84 (EPSG:4326)."""
        gpd, _ = self._load_geographic_libraries()
        try:
            mask_gdf = gpd.read_file(mask_path)
            if mask_gdf.crs != "EPSG:4326":
                mask_gdf = mask_gdf.to_crs("EPSG:4326")
            return mask_gdf
        except Exception as exc:
            raise ValueError(f"Failed to load vector file {mask_path}: {exc}") from exc

    def _load_mask_from_raster(self, mask_path):
        """Convert a raster mask to polygons in WGS84 (EPSG:4326)."""
        rasterio, shapes, shape = self._load_raster_libraries()
        gpd, _ = self._load_geographic_libraries()
        try:
            with rasterio.open(mask_path) as src:
                data = src.read(1)
                mask = (data != 0) & (~pd.isna(data)) & (data != src.nodata)
                if not mask.any():
                    raise ValueError("No valid (non-zero) pixels found in raster")

                geoms = [shape(geom) for geom, _ in shapes(data, mask=mask, transform=src.transform)]
                if not geoms:
                    raise ValueError("No geometries could be extracted from raster")

                mask_gdf = gpd.GeoDataFrame(geometry=geoms, crs=src.crs)
                if mask_gdf.crs != "EPSG:4326":
                    mask_gdf = mask_gdf.to_crs("EPSG:4326")
                return mask_gdf.dissolve()
        except Exception as exc:
            raise ValueError(f"Failed to process raster file {mask_path}: {exc}") from exc

    def _apply_load_result(self, result: Any):
        """Copy normalized loader payload into instance attributes.

        The method applies only attributes present in the payload.
        """
        for attr in (
            "stations_info",
            "sites_info",
            "metadata",
            "data",
            "missing_data_summary",
            "stations",
            "piezometers",
        ):
            if hasattr(result, attr):
                setattr(self, attr, getattr(result, attr))

    def _print_load_summary(
        self,
        *,
        header: str,
        missing_entity_label: str = "stations",
        **extra_values,
    ):
        """Print a standardized loading summary block."""
        print(f"\n=== {header} ===")
        for key, value in extra_values.items():
            label = key.replace("_", " ").capitalize()
            print(f"{label}: {value}")

        data = getattr(self, "data", pd.DataFrame())
        print(f"Total observations: {len(data)}")

        missing = getattr(self, "missing_data_summary", pd.DataFrame())
        if not missing.empty and "missing_days" in missing.columns:
            total_missing = missing["missing_days"].sum()
            print(f"Total missing days across all {missing_entity_label}: {total_missing}")

    @staticmethod
    def _safe_file_token(value: str) -> str:
        """Normalize values used in export filenames."""
        return safe_file_token(value)
