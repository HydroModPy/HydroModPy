"""Derive domain support polygons from one catchment boundary.

This module converts a catchment polygon into the three supports used by the
domain model:
- buffered catchment (for transition/buffer calculations),
- catchment bounding box,
- buffered rectangular box (reference support for raster clipping and gridding).

The buffer distance keeps legacy behavior:
- numeric ``buff_area`` is interpreted as percentage-based scaling,
- string ``buff_area`` is interpreted as explicit meters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import box

from hydromodpy.geographic.geographic_io import ensure_crs


@dataclass(frozen=True)
class CatchmentDomainProducts:
    """Output artifacts produced from one catchment polygon."""

    catchment_area_km2: float
    buffer_distance_m: float
    watershed_buff_shp: str
    watershed_box_shp: str
    watershed_box_buff_shp: str


def _read_dem_resolution(
    dem_init_path: str | Path | None,
    dem_resolution: float | None,
) -> float | None:
    """Resolve DEM resolution in meters from explicit value or DEM metadata."""
    if dem_resolution is not None:
        if float(dem_resolution) <= 0.0:
            raise ValueError("dem_resolution must be > 0")
        return float(dem_resolution)
    if dem_init_path is None:
        return None
    with rasterio.open(str(dem_init_path)) as dem_src:
        return float(abs(dem_src.transform.a))


def _compute_buffer_distance(
    *,
    catchment_area_km2: float,
    buff_area: float | str,
    dem_resolution: float | None,
) -> float:
    """Compute final buffer distance in meters, optionally snapped to DEM grid."""
    # String mode: explicit distance (meters).
    if isinstance(buff_area, str):
        dist = float(buff_area)
        if dist <= 0.0:
            raise ValueError("buff_area distance must be > 0")
        return dist

    # Numeric mode: legacy percent-based scaling from sqrt(area_km2).
    buff_raw = (np.sqrt(float(catchment_area_km2))) * (float(buff_area) / 100.0) * 1000.0
    if buff_raw <= 0.0:
        raise ValueError("buff_area percentage must produce a distance > 0")
    buff_raw = float(int(round(buff_raw)))
    if dem_resolution is None:
        return float(buff_raw)

    # Match legacy Geographic tie-breaking: snap to the closest DEM multiple,
    # and when equidistant choose the lower multiple.
    lower = np.floor(buff_raw / dem_resolution) * dem_resolution
    upper = np.ceil(buff_raw / dem_resolution) * dem_resolution
    if abs(lower - buff_raw) <= abs(upper - buff_raw):
        snapped = lower
    else:
        snapped = upper
    return float(max(snapped, dem_resolution))


def derive_catchment_domain(
    catchment_shp: str | Path,
    output_dir: str | Path,
    *,
    buff_area: float | str,
    dem_init_path: str | Path | None = None,
    dem_resolution: float | None = None,
    crs_project: str | None = None,
    watershed_buff_name: str = "watershed_buff.shp",
    watershed_box_name: str = "watershed_box.shp",
    watershed_box_buff_name: str = "watershed_box_buff.shp",
) -> CatchmentDomainProducts:
    """
    Build catchment-derived polygon products only (no raster processing).

    Parameters
    ----------
    catchment_shp:
        Existing catchment polygon shapefile (e.g. ``watershed.shp``).
    output_dir:
        Directory where output shapefiles are written.
    buff_area:
        Buffer control:
        - numeric value => percentage-based distance (legacy Geographic behavior),
        - string value => direct distance in meters.
    dem_init_path, dem_resolution:
        Used to derive/supply DEM resolution for distance snapping.
        ``dem_resolution`` overrides ``dem_init_path`` when both are provided.
    crs_project:
        Optional CRS override applied to outputs.
    *_name:
        Filenames for generated shapefiles.
    """
    catchment_path = Path(catchment_shp)
    if not catchment_path.exists():
        raise FileNotFoundError(f"catchment_shp not found: {catchment_path}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    catchment_gdf = gpd.read_file(str(catchment_path))
    catchment_gdf = catchment_gdf.loc[:, ~catchment_gdf.columns.duplicated()]
    if catchment_gdf.empty:
        raise ValueError("catchment_shp is empty")

    if catchment_gdf.crs is not None and catchment_gdf.crs.is_geographic:
        raise ValueError(
            "catchment_shp CRS is geographic (degrees). "
            "Use a projected CRS in meters before buffering."
        )

    catchment_area_km2 = float(np.abs(catchment_gdf.geometry.area.sum()) / 1_000_000.0)
    if catchment_area_km2 <= 0.0:
        raise ValueError("catchment area must be > 0")

    res = _read_dem_resolution(dem_init_path, dem_resolution)
    buff_dist = _compute_buffer_distance(
        catchment_area_km2=catchment_area_km2,
        buff_area=buff_area,
        dem_resolution=res,
    )

    target_crs = crs_project or (catchment_gdf.crs.to_string() if catchment_gdf.crs else None)

    watershed_buff_path = out_dir / watershed_buff_name
    watershed_box_path = out_dir / watershed_box_name
    watershed_box_buff_path = out_dir / watershed_box_buff_name

    buff_gdf = catchment_gdf.copy()
    buff_gdf["geometry"] = buff_gdf.geometry.buffer(buff_dist)
    buff_gdf.to_file(str(watershed_buff_path))
    ensure_crs(watershed_buff_path, target_crs)

    xmin, ymin, xmax, ymax = catchment_gdf.total_bounds
    watershed_box_gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[box(xmin, ymin, xmax, ymax)],
        crs=catchment_gdf.crs,
    )
    watershed_box_gdf.to_file(str(watershed_box_path))
    ensure_crs(watershed_box_path, target_crs)

    # Build buffered rectangle from the catchment box envelope.
    box_buff_geom = watershed_box_gdf.geometry.iloc[0].buffer(buff_dist).envelope
    watershed_box_buff_gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[box_buff_geom],
        crs=catchment_gdf.crs,
    )
    watershed_box_buff_gdf.to_file(str(watershed_box_buff_path))
    ensure_crs(watershed_box_buff_path, target_crs)

    return CatchmentDomainProducts(
        catchment_area_km2=catchment_area_km2,
        buffer_distance_m=buff_dist,
        watershed_buff_shp=str(watershed_buff_path),
        watershed_box_shp=str(watershed_box_path),
        watershed_box_buff_shp=str(watershed_box_buff_path),
    )
