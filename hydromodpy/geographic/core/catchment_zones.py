"""Build categorical zone rasters on geographic support.

Purpose
-------
Encode domain regions as integer classes so later model steps can apply
zone-dependent rules (buffer ring, catchment core, outside domain, uniform).

Supported modes
---------------
1. catchment-based zoning from nested polygon supports,
2. uniform zoning directly on DEM support (no buffer/catchment distinction).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

from hydromodpy.geographic.geographic_io import ensure_crs


class CatchmentZoneCode(IntEnum):
    """Discrete zone codes used in output rasters."""

    DOMAIN_OUTSIDE_BUFFER = 1
    BUFFER_RING = 2
    CATCHMENT_CORE = 3
    UNIFORM = 4


@dataclass(frozen=True)
class CatchmentZoneProducts:
    """In-memory zone matrix and optional persisted raster path."""

    zone_codes: np.ndarray
    zone_codes_tif: str | None = None


def _persist_zone_codes(
    *,
    zone_codes: np.ndarray,
    profile: dict,
    zone_codes_tif_path: str | Path | None,
    zone_nodata_code: int,
    crs_project: str | None,
    ref_crs: str | None,
) -> str | None:
    """Persist one zone raster to disk when an output path is requested."""
    if zone_codes_tif_path is None:
        return None
    out_path = Path(zone_codes_tif_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile = profile.copy()
    profile.update(count=1, dtype=np.uint8, nodata=int(zone_nodata_code))
    with rasterio.open(str(out_path), "w", **profile) as dst:
        dst.write(zone_codes, 1)
    ensure_crs(out_path, crs_project or ref_crs)
    return str(out_path)


def _read_polygon(path: str | Path) -> gpd.GeoDataFrame:
    """Read one polygon shapefile and ensure it is non-empty."""
    shp = Path(path)
    if not shp.exists():
        raise FileNotFoundError(f"polygon shapefile not found: {shp}")
    gdf = gpd.read_file(str(shp))
    gdf = gdf.loc[:, ~gdf.columns.duplicated()]
    if gdf.empty:
        raise ValueError(f"polygon shapefile is empty: {shp}")
    return gdf


def build_catchment_zone_codes(
    *,
    catchment_shp: str | Path,
    watershed_buff_shp: str | Path,
    watershed_box_buff_shp: str | Path,
    reference_raster_path: str | Path,
    zone_codes_tif_path: str | Path | None = None,
    zone_nodata_code: int = 0,
    crs_project: str | None = None,
) -> CatchmentZoneProducts:
    """Rasterize catchment zones on the grid of a reference raster.

    Zone assignment uses overwrite priority (last write wins):
    1. domain rectangle    -> ``DOMAIN_OUTSIDE_BUFFER``
    2. buffered catchment  -> ``BUFFER_RING``
    3. core catchment      -> ``CATCHMENT_CORE``
    """
    catchment_gdf = _read_polygon(catchment_shp)
    buff_gdf = _read_polygon(watershed_buff_shp)
    box_buff_gdf = _read_polygon(watershed_box_buff_shp)

    with rasterio.open(str(reference_raster_path)) as ref_src:
        transform = ref_src.transform
        shape = (ref_src.height, ref_src.width)
        profile = ref_src.profile.copy()
        ref_crs = ref_src.crs.to_string() if ref_src.crs is not None else None

    zone_codes = np.full(shape, fill_value=int(zone_nodata_code), dtype=np.uint8)

    # Rasterize all supports on the exact same grid before class assignment.
    box_mask = rasterize(
        [(geom, 1) for geom in box_buff_gdf.geometry],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    buff_mask = rasterize(
        [(geom, 1) for geom in buff_gdf.geometry],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    catch_mask = rasterize(
        [(geom, 1) for geom in catchment_gdf.geometry],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )

    zone_codes[box_mask == 1] = int(CatchmentZoneCode.DOMAIN_OUTSIDE_BUFFER)
    zone_codes[buff_mask == 1] = int(CatchmentZoneCode.BUFFER_RING)
    zone_codes[catch_mask == 1] = int(CatchmentZoneCode.CATCHMENT_CORE)

    output_path = _persist_zone_codes(
        zone_codes=zone_codes,
        profile=profile,
        zone_codes_tif_path=zone_codes_tif_path,
        zone_nodata_code=zone_nodata_code,
        crs_project=crs_project,
        ref_crs=ref_crs,
    )

    return CatchmentZoneProducts(zone_codes=zone_codes, zone_codes_tif=output_path)


def build_uniform_zone_codes(
    *,
    reference_raster_path: str | Path,
    zone_codes_tif_path: str | Path | None = None,
    zone_nodata_code: int = 0,
    crs_project: str | None = None,
) -> CatchmentZoneProducts:
    """Build one uniform zone raster on the valid footprint of a reference DEM."""
    with rasterio.open(str(reference_raster_path)) as ref_src:
        values = np.asarray(ref_src.read(1), dtype=float)
        nodata = ref_src.nodata
        shape = (ref_src.height, ref_src.width)
        profile = ref_src.profile.copy()
        ref_crs = ref_src.crs.to_string() if ref_src.crs is not None else None

    valid_mask = np.isfinite(values)
    if nodata is not None:
        valid_mask &= values != float(nodata)

    zone_codes = np.full(shape, fill_value=int(zone_nodata_code), dtype=np.uint8)
    zone_codes[valid_mask] = int(CatchmentZoneCode.UNIFORM)

    output_path = _persist_zone_codes(
        zone_codes=zone_codes,
        profile=profile,
        zone_codes_tif_path=zone_codes_tif_path,
        zone_nodata_code=zone_nodata_code,
        crs_project=crs_project,
        ref_crs=ref_crs,
    )

    return CatchmentZoneProducts(zone_codes=zone_codes, zone_codes_tif=output_path)
