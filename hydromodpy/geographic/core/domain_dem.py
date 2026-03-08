"""Clip the regional DEM to the buffered rectangular domain support.

The output raster is the common elevation support used by domain-level
preprocessing and by the in-memory topographic surface builder.
"""

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
    wbt_tool: object | None = None,
) -> str:
    """Clip source DEM to domain rectangle and normalize metadata.

    Parameters
    ----------
    dem_init_path:
        Regional/source DEM.
    box_buff_shp:
        Buffered rectangular support polygon.
    output_dem_path:
        Clipped DEM path.
    crs_project:
        Optional CRS override.
    nodata:
        Nodata value enforced on output.
    wbt_tool:
        Optional Whitebox-like object for testing/injection.

    Returns
    -------
    str
        Path to the clipped DEM raster.
    """
    tool = wbt if wbt_tool is None else wbt_tool

    src_dem = str(dem_init_path)
    clip_poly = str(box_buff_shp)
    dst_dem = str(output_dem_path)
    Path(dst_dem).parent.mkdir(parents=True, exist_ok=True)

    # `maintain_dimensions=False` keeps only the effective clipped extent.
    tool.clip_raster_to_polygon(
        src_dem,
        clip_poly,
        dst_dem,
        maintain_dimensions=False,
    )

    ensure_crs(dst_dem, crs_project)
    tool.modify_no_data_value(dst_dem, new_value=float(nodata))
    return dst_dem
