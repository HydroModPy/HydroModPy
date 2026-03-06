"""Define and rasterize the 3 catchment zone types on one raster support.

The output matrix uses three explicit classes:
- ``DOMAIN_OUTSIDE_BUFFER``: in rectangular domain, outside buffered catchment,
- ``BUFFER_RING``: in buffered catchment, outside core catchment,
- ``CATCHMENT_CORE``: inside core catchment polygon.
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
    """Discrete zone codes used in zone rasters."""

    DOMAIN_OUTSIDE_BUFFER = 1
    BUFFER_RING = 2
    CATCHMENT_CORE = 3


@dataclass(frozen=True)
class CatchmentZoneProducts:
    """Zone extraction products for one raster support."""

    zone_codes: np.ndarray
    zone_codes_tif: str | None = None


def _read_polygon(path: str | Path) -> gpd.GeoDataFrame:
    """Read one polygon shapefile and reject empty content."""
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
    """
    Rasterize the 3 catchment zone types on a reference raster grid.

    Parameters
    ----------
    catchment_shp : str | Path
        Path to the core catchment polygon shapefile (typically ``.shp``).
        Expected content: polygon or multipolygon geometry in a projected CRS.
    watershed_buff_shp : str | Path
        Path to the buffered catchment polygon shapefile (typically ``.shp``).
        Same CRS as ``catchment_shp`` and compatible with the reference raster.
    watershed_box_buff_shp : str | Path
        Path to the buffered rectangular domain shapefile (typically ``.shp``).
        Defines the outer domain support used for zone code 1.
    reference_raster_path : str | Path
        Path to a raster readable by ``rasterio`` (usually GeoTIFF ``.tif``).
        This raster provides the target grid geometry:
        - shape (height, width),
        - affine transform (pixel alignment),
        - output metadata profile.
    zone_codes_tif_path : str | Path | None, optional
        Optional output path for the zone code raster (GeoTIFF recommended).
        If ``None``, no file is written and only the in-memory array is returned.
    zone_nodata_code : int, optional
        Nodata / background code used to initialize cells outside the domain.
        Stored as ``uint8`` in the output raster, so values should be in ``[0, 255]``.
    crs_project : str | None, optional
        CRS string to force on the written output file (example: ``"EPSG:2154"``).
        If ``None``, CRS is copied from ``reference_raster_path`` when available.

    Returns
    -------
    CatchmentZoneProducts
        - ``zone_codes``: ``np.ndarray`` of shape ``(height, width)`` and dtype ``uint8``.
        - ``zone_codes_tif``: written raster path when ``zone_codes_tif_path`` is provided,
          otherwise ``None``.

    Notes
    -----
    Zone overwrite priority (last assignment wins):
    1. ``DOMAIN_OUTSIDE_BUFFER`` (inside ``watershed_box_buff_shp``)
    2. ``BUFFER_RING`` (inside ``watershed_buff_shp``)
    3. ``CATCHMENT_CORE`` (inside ``catchment_shp``)
    """
    # Step 1 - Read source polygons used to build the 3-zone hierarchy.
    catchment_gdf = _read_polygon(catchment_shp)
    buff_gdf = _read_polygon(watershed_buff_shp)
    box_buff_gdf = _read_polygon(watershed_box_buff_shp)

    # Step 2 - Read output raster support (transform + shape + profile).
    with rasterio.open(str(reference_raster_path)) as ref_src:
        transform = ref_src.transform
        shape = (ref_src.height, ref_src.width)
        profile = ref_src.profile.copy()
        ref_crs = ref_src.crs.to_string() if ref_src.crs is not None else None

    # Step 3 - Rasterize each polygon layer on the same support grid.
    zone_codes = np.full(
        shape,
        fill_value=int(zone_nodata_code),
        dtype=np.uint8,
    )
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

    # Step 4 - Apply class overwrite order from coarse support to core catchment.
    zone_codes[box_mask == 1] = int(CatchmentZoneCode.DOMAIN_OUTSIDE_BUFFER)
    zone_codes[buff_mask == 1] = int(CatchmentZoneCode.BUFFER_RING)
    zone_codes[catch_mask == 1] = int(CatchmentZoneCode.CATCHMENT_CORE)

    # Step 5 - Optionally persist zone matrix to GeoTIFF.
    output_path: str | None = None
    if zone_codes_tif_path is not None:
        out_path = Path(zone_codes_tif_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        profile.update(
            count=1,
            dtype=np.uint8,
            nodata=int(zone_nodata_code),
        )
        with rasterio.open(str(out_path), "w", **profile) as dst:
            dst.write(zone_codes, 1)
        ensure_crs(out_path, crs_project or ref_crs)
        output_path = str(out_path)

    # Step 6 - Return in-memory matrix and optional artifact path.
    return CatchmentZoneProducts(
        zone_codes=zone_codes,
        zone_codes_tif=output_path,
    )
