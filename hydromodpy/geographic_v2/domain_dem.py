"""Domain DEM clipping utilities for geographic V2."""

from __future__ import annotations

from pathlib import Path

import whitebox

from hydromodpy.geographic.geographic_io import ensure_crs

wbt = whitebox.WhiteboxTools()
wbt.verbose = False


def clip_dem_to_box_buffer(
    *,
    dem_init_path: str | Path,
    box_buff_shp: str | Path,
    output_dem_path: str | Path,
    crs_project: str | None = None,
    nodata: float = -9999.0,
) -> str:
    """Clip the input DEM to the buffered rectangular domain polygon."""
    # Step 1 - Normalize paths and prepare destination folder.
    src_dem = str(dem_init_path)
    clip_poly = str(box_buff_shp)
    dst_dem = str(output_dem_path)
    Path(dst_dem).parent.mkdir(parents=True, exist_ok=True)

    # Step 2 - Clip source DEM to polygon extent.
    wbt.clip_raster_to_polygon(
        src_dem,
        clip_poly,
        dst_dem,
        maintain_dimensions=False,
    )

    # Step 3 - Enforce CRS and nodata conventions used by downstream domain logic.
    ensure_crs(dst_dem, crs_project)
    wbt.modify_no_data_value(dst_dem, new_value=float(nodata))
    return dst_dem
