"""Clip the regional DEM to the buffered rectangular domain support.

The output raster is the common elevation support used by domain-level
preprocessing and by the in-memory topographic surface builder.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.backends import WhiteboxBackend, get_whitebox_backend

from hydromodpy.geographic.geographic_io import ensure_crs


def clip_dem_to_box_buffer(
    *,
    dem_init_path: str | Path,
    box_buff_shp: str | Path,
    output_dem_path: str | Path,
    crs_project: str | None = None,
    nodata: float = -9999.0,
    backend: WhiteboxBackend | None = None,
    wbt_tool: WhiteboxBackend | None = None,
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
    wbt_tool:
        Legacy alias for ``backend`` kept for backward compatibility.

    Returns
    -------
    str
        Path to the clipped DEM raster.
    """
    if backend is not None and wbt_tool is not None:
        raise ValueError("Pass either 'backend' or legacy alias 'wbt_tool', not both.")
    tool = get_whitebox_backend() if backend is None and wbt_tool is None else (backend or wbt_tool)

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
