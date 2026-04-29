"""Hydrography variable manager: fetch, clip, rasterise."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

from hydromodpy.core.logging import get_logger
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)
from hydromodpy.data.variables.hydrography.result import HydrographyResult
from hydromodpy.spatial.delineation import get_whitebox_backend

if TYPE_CHECKING:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

logger = get_logger(__name__)


class HydrographyManager:
    """Load, clip, and rasterise hydrography vector data."""

    VARIABLE_NAME = "hydrography"

    def __init__(
        self,
        *,
        config: HydrographyConfig,
        geographic: object,
        out_path: str | Path,
        catalog: DataCatalog | None = None,
        data_dir: Path | None = None,
        stable_folder: str | Path | None = None,
    ) -> None:
        self.config = config
        self.geographic = geographic
        from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR

        base = Path(stable_folder) if stable_folder else Path(out_path) / PREPROCESSING_DIR
        self._data_folder = base / "hydrography"
        self._data_folder.mkdir(parents=True, exist_ok=True)
        self._backend = get_whitebox_backend()
        self._catalog = catalog
        self._data_dir = data_dir

    def load(self) -> HydrographyResult:
        """Execute the full pipeline: fetch -> reproject -> clip -> rasterise."""
        # 1. Fetch from each source
        vector_gdfs: list[gpd.GeoDataFrame] = []
        tif_path: Path | None = None

        for src in self.config.sources:
            result = self._fetch_from_source(src)
            if isinstance(result, Path):
                tif_path = result
            elif not result.empty:
                vector_gdfs.append(result)

        # TIF custom shortcut - skip vector pipeline
        if tif_path is not None:
            return self._load_from_tif(tif_path)

        if not vector_gdfs:
            raise ValueError("All hydrography sources returned empty results.")

        combined = gpd.GeoDataFrame(pd.concat(vector_gdfs, ignore_index=True))
        if combined.crs is None:
            combined = combined.set_crs("EPSG:4326")

        # 2. Reproject to project CRS
        project_crs = getattr(self.geographic, "crs_proj", None) or getattr(
            self.geographic, "crs_project", None
        )
        if project_crs and str(combined.crs) != str(project_crs):
            combined = combined.to_crs(project_crs)

        # 3. Clip to watershed
        watershed = gpd.read_file(self.geographic.watershed_shp)
        clipped = gpd.clip(combined, watershed)

        # 4. Save clipped vector
        streams_path = self._data_folder / "streams.shp"
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Column names longer than 10 characters")
            clipped.to_file(streams_path)

        # 5. Rasterise
        rasterize_field = self.config.sources[0].rasterize_field
        tif_out = self._rasterize(streams_path, rasterize_field)

        # 6. Read array
        streams_array = self._read_tif_array(tif_out)

        return HydrographyResult(
            streams=str(streams_path),
            tif_streams=str(tif_out),
            streams_array=streams_array,
        )

    # ------------------------------------------------------------------
    # TIF pipeline
    # ------------------------------------------------------------------

    def _load_from_tif(self, tif_path: Path) -> HydrographyResult:
        """Clip a pre-rasterised TIF to the watershed and return the result."""
        from rasterio.mask import mask as rio_mask
        from shapely.ops import unary_union

        watershed = gpd.read_file(self.geographic.watershed_shp)

        # Reproject watershed geometry into the CRS of the TIF
        with rasterio.open(str(tif_path)) as src:
            tif_crs = src.crs

        if str(watershed.crs) != str(tif_crs):
            watershed = watershed.to_crs(tif_crs)

        geom = [unary_union(watershed.geometry)]

        with rasterio.open(str(tif_path)) as src:
            out_image, out_transform = rio_mask(
                src,
                geom,
                crop=True,
                nodata=-32768,
            )
            out_meta = src.meta.copy()
            out_meta.update(
                height=out_image.shape[1],
                width=out_image.shape[2],
                transform=out_transform,
                nodata=-32768,
            )

        out_tif = self._data_folder / "streams.tif"
        with rasterio.open(str(out_tif), "w", **out_meta) as dst:
            dst.write(out_image)

        arr = out_image[0].astype(float)
        arr[arr < 0] = np.nan

        return HydrographyResult(
            streams=None,
            tif_streams=str(out_tif),
            streams_array=arr,
        )

    # ------------------------------------------------------------------
    # Source dispatch
    # ------------------------------------------------------------------

    def _fetch_from_source(
        self,
        source_cfg: HydrographySourceConfig,
    ) -> gpd.GeoDataFrame | Path:
        """Dispatch to the correct loader/API for *source_cfg*."""
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.hydrography.custom import load_custom

            return load_custom(source_cfg)

        bbox = self._get_bbox_wgs84()

        # Cache check (API sources only)
        if not source_cfg.force_refresh:
            cached = self._try_load_cached(source_cfg.source, bbox)
            if cached is not None:
                return cached

        # Fetch from API
        gdf = self._fetch_api(source_cfg, bbox)

        # Persist + register in catalog
        self._persist_and_register(gdf, source_cfg.source, bbox)

        return gdf

    def _fetch_api(
        self,
        source_cfg: HydrographySourceConfig,
        bbox: tuple[float, float, float, float],
    ) -> gpd.GeoDataFrame:
        """Call the appropriate API fetch function."""
        if source_cfg.source == "osm":
            from hydromodpy.data.variables.hydrography.apis.osm import fetch

            return fetch(source_cfg, bbox)

        if source_cfg.source == "bdtopage":
            from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

            return fetch(source_cfg, bbox)

        if source_cfg.source == "euhydro":
            from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

            return fetch(source_cfg, bbox)

        raise ValueError(f"Unknown hydrography source: {source_cfg.source!r}")

    # ------------------------------------------------------------------
    # Catalog cache helpers
    # ------------------------------------------------------------------

    def _try_load_cached(
        self,
        source: str,
        bbox: tuple[float, float, float, float],
    ) -> gpd.GeoDataFrame | None:
        """Return cached GeoDataFrame if the catalog has a superset entry."""
        if self._catalog is None:
            return None
        entry = self._catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            bbox=bbox,
        )
        if entry is None:
            return None
        cached_path = Path(entry.file_path)
        if not cached_path.exists():
            return None
        logger.info("Cache hit for hydrography/%s: %s", source, cached_path)
        return gpd.read_file(cached_path)

    def _persist_and_register(
        self,
        gdf: gpd.GeoDataFrame,
        source: str,
        bbox: tuple[float, float, float, float],
    ) -> None:
        """Save raw API result (EPSG:4326) and register in catalog."""
        if self._catalog is None or self._data_dir is None:
            return
        self._data_dir.mkdir(parents=True, exist_ok=True)

        fname = f"{source}_{bbox[0]:.4f}_{bbox[1]:.4f}_{bbox[2]:.4f}_{bbox[3]:.4f}.gpkg"
        out_path = self._data_dir / fname

        # Ensure EPSG:4326 before persisting
        if gdf.crs is not None and str(gdf.crs) != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        elif gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")

        gdf.to_file(out_path, driver="GPKG")

        entry_id = self._catalog.register(
            variable=self.VARIABLE_NAME,
            source=source,
            file_path=str(out_path),
            bbox=bbox,
            crs="EPSG:4326",
            is_custom=False,
        )
        self._catalog.subsume_entries(
            variable=self.VARIABLE_NAME,
            source=source,
            bbox=bbox,
            date_start=None,
            date_end=None,
            exclude_id=entry_id,
        )

    # ------------------------------------------------------------------
    # Rasterise / read helpers
    # ------------------------------------------------------------------

    def _rasterize(self, streams_path: Path, field: str) -> Path:
        """Rasterise the clipped vector layer using the WhiteBox backend."""
        shp_base = gpd.read_file(streams_path)
        shp_type = shp_base.geometry.type.iloc[0] if not shp_base.empty else "LineString"

        tif_path = self._data_folder / "streams.tif"

        if field not in shp_base.columns:
            logger.debug(
                "Rasterize field %r not found in data; creating synthetic sequential field.",
                field,
            )
            shp_base[field] = range(1, len(shp_base) + 1)
        else:
            try:
                shp_base[field] = pd.to_numeric(shp_base[field])
            except (ValueError, KeyError):
                pass
        shp_base.to_file(streams_path)

        watershed_dem = self.geographic.watershed_dem

        if shp_type in ("MultiPolygon", "Polygon"):
            logger.debug("Rasterising polygon geometry: %s", shp_type)
            self._backend.raster.vector_polygons_to_raster(
                str(streams_path),
                str(tif_path),
                field=field,
                base=watershed_dem,
            )
        elif shp_type in ("MultiLineString", "LineString", "Line"):
            logger.debug("Rasterising line geometry: %s", shp_type)
            self._backend.raster.vector_lines_to_raster(
                str(streams_path),
                str(tif_path),
                field=field,
                base=watershed_dem,
            )
        elif shp_type in ("Point", "MultiPoint"):
            logger.debug("Rasterising point geometry: %s", shp_type)
            self._backend.raster.vector_points_to_raster(
                str(streams_path),
                str(tif_path),
                field=field,
                base=watershed_dem,
            )
        else:
            raise ValueError(f"Unsupported geometry type: {shp_type}")

        self._backend.raster.set_nodata_value(str(tif_path), str(tif_path), back_value=-32768)

        # Also create a point shapefile from the raster (used downstream)
        pt_streams = self._data_folder / "streams_pt.shp"
        self._backend.delineation.raster_to_vector_points(str(tif_path), str(pt_streams))

        return tif_path

    @staticmethod
    def _read_tif_array(tif_path: Path) -> np.ndarray:
        with rasterio.open(str(tif_path)) as ds:
            arr = ds.read(1).astype(float)
        arr[arr < 0] = np.nan
        return arr

    def _get_bbox_wgs84(self) -> tuple[float, float, float, float]:
        """Derive a WGS84 bounding box from the geographic config."""
        watershed = gpd.read_file(self.geographic.watershed_shp)
        if str(watershed.crs) != "EPSG:4326":
            watershed = watershed.to_crs("EPSG:4326")
        bounds = watershed.total_bounds  # (minx, miny, maxx, maxy)
        return (bounds[0], bounds[1], bounds[2], bounds[3])
