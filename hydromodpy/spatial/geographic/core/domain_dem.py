"""Clip a regional DEM to canonical domain rectangular support.

Purpose
-------
Produce the DEM raster used as common elevation support by downstream domain
steps and surface builders.

Pipeline position
-----------------
Runs after domain support polygons are built (box-buffer polygon available).
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.delineation import (
    WhiteboxWorkflowsBackend,
    get_whitebox_backend,
)
from hydromodpy.spatial.geographic.geographic_io import ensure_crs


def clip_dem_to_box_buffer(
    *,
    dem_init_path: str | Path,
    box_buff_shp: str | Path,
    output_dem_path: str | Path,
    crs_project: str | None = None,
    nodata: float = -9999.0,
    backend: WhiteboxWorkflowsBackend | None = None,
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
    backend:
        Optional Whitebox backend for runtime/tests.
    Returns
    -------
    str
        Path to the clipped DEM raster.
    """
    tool = get_whitebox_backend() if backend is None else backend

    src_dem = str(dem_init_path)
    clip_poly = str(box_buff_shp)
    dst_dem = str(output_dem_path)
    Path(dst_dem).parent.mkdir(parents=True, exist_ok=True)

    if isinstance(tool, WhiteboxWorkflowsBackend):
        clipped = tool.raster.clip_raster_to_polygon_raster(
            tool.raster.read_raster(src_dem),
            tool.raster.read_vector(clip_poly),
            maintain_dimensions=False,
        )
        clipped = tool.raster.modify_no_data_value_raster(clipped, new_value=float(nodata))
        tool.raster.write_raster(clipped, dst_dem)
    else:
        # `maintain_dimensions=False` keeps only the effective clipped extent.
        tool.raster.clip_raster_to_polygon(
            src_dem,
            clip_poly,
            dst_dem,
            maintain_dimensions=False,
        )
        tool.raster.modify_no_data_value(dst_dem, new_value=float(nodata))

    ensure_crs(dst_dem, crs_project)
    return dst_dem
