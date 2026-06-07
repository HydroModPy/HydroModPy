"""Build domain artifacts directly from a DEM extent.

Purpose
-------
Support ``catch_def='dem'`` mode, where the DEM itself defines the model
domain and no watershed delineation is required.

Produced artifacts
------------------
Canonical watershed/domain polygons plus copied DEM support, all aligned with
the same path contracts as delineated workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from shapely.geometry import box, shape
from shapely.ops import unary_union

from hydromodpy.spatial.geographic.geographic_io import ensure_crs
from hydromodpy.spatial.geographic.geographic_paths import GeographicPaths


@dataclass(frozen=True)
class DirectDemDomainProducts:
    """Artifacts produced when the model domain comes directly from a DEM."""

    watershed_shp: str
    watershed_buff_shp: str
    watershed_box_shp: str
    watershed_box_buff_shp: str
    watershed_box_buff_dem: str
    domain_area_km2: float


def _valid_dem_mask(values: np.ndarray, nodata: float | None) -> np.ndarray:
    """Return the active-domain mask from DEM values and nodata metadata."""
    mask = np.isfinite(values)
    if nodata is not None:
        mask &= values != float(nodata)
    return mask


def _write_raster_copy(
    *,
    src_path: str | Path,
    dst_path: str | Path,
    crs_project: str | None,
) -> None:
    """Copy one raster to the canonical output location and normalize CRS metadata."""
    with rasterio.open(str(src_path)) as src:
        profile = src.profile.copy()
        data = src.read(1)

    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(str(dst), "w", **profile) as out:
        out.write(data, 1)
    ensure_crs(dst, crs_project)


def build_direct_dem_domain(
    *,
    dem_init_path: str | Path,
    paths: GeographicPaths,
    crs_project: str | None = None,
) -> DirectDemDomainProducts:
    """Build canonical domain artifacts directly from one DEM input.

    Outputs are intentionally compatible with the V2 domain runner:
    - ``watershed.shp`` is the polygonized raster footprint of valid DEM cells,
    - ``watershed_buff.shp`` is identical in ``dem`` mode,
    - ``watershed_box.shp`` and ``watershed_box_buff.shp`` are the raster bounds,
    - ``watershed_box_buff_dem.tif`` is the normalized DEM copy used by domain code.
    """
    dem_path = Path(dem_init_path)
    with rasterio.open(str(dem_path)) as src:
        values = np.asarray(src.read(1), dtype=float)
        nodata = src.nodata
        transform = src.transform
        raster_bounds = src.bounds
        src_crs = src.crs.to_string() if src.crs is not None else None

    valid_mask = _valid_dem_mask(values, nodata)
    if not np.any(valid_mask):
        raise ValueError("DEM mode requires at least one valid cell in dem_init_path")

    footprint_parts = [
        shape(geom)
        for geom, value in shapes(
            valid_mask.astype(np.uint8),
            mask=valid_mask,
            transform=transform,
        )
        if int(value) == 1
    ]
    if not footprint_parts:
        raise ValueError("Unable to build domain footprint from DEM valid cells")

    footprint = unary_union(footprint_parts)
    target_crs = crs_project or src_crs

    watershed_gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[footprint],
        crs=src_crs,
    )
    watershed_gdf.to_file(paths.watershed_shp)
    ensure_crs(paths.watershed_shp, target_crs)

    watershed_buff_path = Path(paths.geographic_path) / "watershed_buff.shp"
    watershed_gdf.to_file(str(watershed_buff_path))
    ensure_crs(watershed_buff_path, target_crs)

    raster_box = box(
        float(raster_bounds.left),
        float(raster_bounds.bottom),
        float(raster_bounds.right),
        float(raster_bounds.top),
    )
    box_gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[raster_box],
        crs=src_crs,
    )
    box_gdf.to_file(paths.watershed_box_shp)
    ensure_crs(paths.watershed_box_shp, target_crs)
    box_gdf.to_file(paths.box_buff)
    ensure_crs(paths.box_buff, target_crs)

    _write_raster_copy(
        src_path=dem_path,
        dst_path=paths.watershed_box_buff_dem,
        crs_project=target_crs,
    )

    return DirectDemDomainProducts(
        watershed_shp=paths.watershed_shp,
        watershed_buff_shp=str(watershed_buff_path),
        watershed_box_shp=paths.watershed_box_shp,
        watershed_box_buff_shp=paths.box_buff,
        watershed_box_buff_dem=paths.watershed_box_buff_dem,
        domain_area_km2=float(footprint.area / 1_000_000.0),
    )
