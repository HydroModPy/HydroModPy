"""Import and normalize an externally provided catchment polygon.

Purpose
-------
Support workflows where catchment delineation is already available outside
HydroModPy and only needs to be standardized for internal pipeline contracts.

Pipeline position
-----------------
Used when ``catch_def='from_polyg_shp'`` in the geographic workflow.

Main responsibilities
---------------------
- copy the input polygon to canonical ``watershed.shp`` location,
- remove duplicate attribute columns often found in shapefile exports,
- enforce CRS metadata expected by downstream steps.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.geographic.geographic_io import (
    ensure_crs,
    write_shapefile_without_duplicate_columns,
)


def extract_catchment_from_polygon(
    *,
    polyg_shp_path: str | Path,
    output_shp_path: str | Path,
    crs_project: str | None = None,
) -> str:
    """Copy and sanitize one input catchment polygon shapefile.

    Parameters
    ----------
    polyg_shp_path:
        Source catchment polygon path.
    output_shp_path:
        Canonical destination path (usually ``watershed.shp``).
    crs_project:
        Optional CRS override to enforce on output metadata.

    Returns
    -------
    str
        Path to the sanitized output shapefile.
    """
    src = Path(polyg_shp_path)
    dst = Path(output_shp_path)
    if not src.exists():
        raise FileNotFoundError(f"polyg_shp_path not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Keep schema stable by dropping duplicate column names.
    write_shapefile_without_duplicate_columns(src, dst)

    # Enforce output CRS metadata when requested by caller.
    ensure_crs(dst, crs_project)
    return str(dst)
