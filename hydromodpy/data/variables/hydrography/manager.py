"""Hydrography variable manager: fetch, clip, rasterise.

What this manager needs, and where each piece comes from
--------------------------------------------------------
It used to read a ``geographic`` object for **three** distinct things, only one
of which was an extent: the project CRS, the polygon it clips to, and the
reference grid it rasterises onto. The object is gone and the three are named:

- the clip shape and the request box are one file, ``config.mask_path``, read
  through :func:`~hydromodpy.data.common.source_extent.mask_geometry`;
- the project CRS is **not an input at all** -- the mask says which frame the
  clip happens in, and the network is reprojected into it. On a project run
  that is the same answer, the delineated watershed being written in the
  project CRS; off a project run it is the only answer that means anything,
  because a box and a polygon in two different frames do not intersect;
- the reference grid is ``base_raster``, a constructor argument beside
  ``out_path``, because it is not something a user configures: it is the grid
  the project already has.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import xarray as xr

from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.source_extent import mask_extent_in, mask_geometry
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FILENAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_VECTOR_FILENAME,
)

if TYPE_CHECKING:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

logger = get_logger(__name__)


def fetch_api_source(
    source_cfg: HydrographySourceConfig,
    bbox_wgs84: tuple[float, float, float, float],
) -> gpd.GeoDataFrame:
    """Dispatch one API source to its fetch function, in EPSG:4326.

    Module level rather than a method because the stream burn resolver needs the
    same dispatch before any manager exists: it downloads on an outlet box, at a
    point in the pipeline where the watershed a manager clips against is not
    delineated yet.
    """
    if source_cfg.source == "osm":
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        return fetch(source_cfg, bbox_wgs84)

    if source_cfg.source == "bdtopage":
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        return fetch(source_cfg, bbox_wgs84)

    if source_cfg.source == "euhydro":
        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

        return fetch(source_cfg, bbox_wgs84)

    raise ValueError(f"Unknown hydrography source: {source_cfg.source!r}")


class HydrographyManager:
    """Load, clip, and rasterise hydrography vector data."""

    VARIABLE_NAME = "hydrography"

    def __init__(
        self,
        *,
        config: HydrographyConfig,
        out_path: str | Path,
        base_raster: str | Path | None = None,
        catalog: DataCatalogDuckDB | None = None,
        data_dir: Path | None = None,
        stable_folder: str | Path | None = None,
    ) -> None:
        self.config = config
        self._base_raster = base_raster
        from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR
        from hydromodpy.spatial.delineation import get_whitebox_backend

        base = Path(stable_folder) if stable_folder else Path(out_path) / PREPROCESSING_DIR
        self._data_folder = base / "hydrography"
        self._data_folder.mkdir(parents=True, exist_ok=True)
        self._backend = get_whitebox_backend()
        self._catalog = catalog
        self._data_dir = data_dir

    def load(self) -> LoadResult:
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

        # 2. Reproject into the frame the mask is in, then clip to its shape
        mask_shape, mask_crs = mask_geometry(self._require_mask_path())
        if str(combined.crs) != str(mask_crs):
            combined = combined.to_crs(mask_crs)
        clipped = gpd.clip(combined, mask_shape)

        # 3. Save clipped vector
        streams_path = self._data_folder / HYDROGRAPHIC_NETWORK_REFERENCE_VECTOR_FILENAME
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Column names longer than 10 characters")
            clipped.to_file(streams_path)

        # 4. Rasterise
        rasterize_field = self.config.sources[0].rasterize_field
        tif_out = self._rasterize(streams_path, rasterize_field)

        # 5. Read array
        raster_values = self._read_tif_array(tif_out)

        return self._build_load_result(
            raster_values,
            raster_path=tif_out,
            vector_path=streams_path,
        )

    # ------------------------------------------------------------------
    # TIF pipeline
    # ------------------------------------------------------------------

    def _load_from_tif(self, tif_path: Path) -> LoadResult:
        """Clip a pre-rasterised TIF to the mask and return the result."""
        from rasterio.mask import mask as rio_mask

        mask_shape, mask_crs = mask_geometry(self._require_mask_path())

        # Reproject the mask geometry into the CRS of the TIF
        with rasterio.open(str(tif_path)) as src:
            tif_crs = src.crs

        mask_gdf = gpd.GeoDataFrame(geometry=[mask_shape], crs=mask_crs)
        if str(mask_crs) != str(tif_crs):
            mask_gdf = mask_gdf.to_crs(tif_crs)

        geom = [mask_gdf.geometry.iloc[0]]

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

        out_tif = self._data_folder / HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FILENAME
        with rasterio.open(str(out_tif), "w", **out_meta) as dst:
            dst.write(out_image)

        arr = out_image[0].astype(float)
        arr[arr < 0] = np.nan

        return self._build_load_result(
            arr,
            raster_path=out_tif,
            vector_path=None,
        )

    def _build_load_result(
        self,
        raster_values: np.ndarray,
        *,
        raster_path: Path,
        vector_path: Path | None,
    ) -> LoadResult:
        """Build the standard hydrography load result."""
        bbox, crs = self._raster_bbox_crs(raster_path)
        data = xr.Dataset(
            data_vars={
                HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME: (
                    ("y", "x"),
                    raster_values,
                )
            }
        )
        record = FieldRecord(
            variable=HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
            source=self.VARIABLE_NAME,
            unit="",
            data=data,
            bbox=bbox,
            crs=crs,
            metadata={
                "raster_path": str(raster_path),
                "vector_path": str(vector_path) if vector_path is not None else None,
                "array_name": HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
            },
        )
        return LoadResult(fields=[record])

    @staticmethod
    def _raster_bbox_crs(raster_path: Path) -> tuple[tuple[float, float, float, float], str]:
        with rasterio.open(str(raster_path)) as ds:
            bounds = ds.bounds
            crs = str(ds.crs) if ds.crs is not None else ""
        return (bounds.left, bounds.bottom, bounds.right, bounds.top), crs

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
        return fetch_api_source(source_cfg, bbox)

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
        logger.debug("Cache hit for hydrography/%s: %s", source, cached_path)
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

        if self._base_raster is None:
            raise ValueError(
                "Rasterising a hydrography network needs a reference grid; pass "
                "base_raster to HydrographyManager."
            )
        watershed_dem = str(self._base_raster)

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

    def _require_mask_path(self) -> Path:
        """The one file that says where this request is, or a refusal naming it."""
        mask_path = getattr(self.config, "mask_path", None)
        if not mask_path:
            raise ValueError(
                "Hydrography clips its network to a mask and asks its sources over the "
                "same box; set data.hydrography.mask_path to a SHP/GPKG/GeoJSON/TIF."
            )
        return Path(mask_path)

    def _get_bbox_wgs84(self) -> tuple[float, float, float, float]:
        """The request box in WGS84, which is what the three APIs are asked in."""
        return mask_extent_in(self._require_mask_path(), "EPSG:4326").bbox
