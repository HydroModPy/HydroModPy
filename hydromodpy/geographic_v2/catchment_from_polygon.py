"""Normalize an existing catchment polygon to HydroModPy canonical output path."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.geographic.geographic_io import ensure_crs, write_shapefile_without_duplicate_columns


def extract_catchment_from_polygon(
    *,
    polyg_shp_path: str | Path,
    output_shp_path: str | Path,
    crs_project: str | None = None,
) -> str:
    """Copy one polygon shapefile to the canonical watershed output path."""
    # Step 1 - Validate source file and create destination folder.
    src = Path(polyg_shp_path)
    dst = Path(output_shp_path)
    if not src.exists():
        raise FileNotFoundError(f"polyg_shp_path not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Step 2 - Write a clean shapefile without duplicate columns.
    write_shapefile_without_duplicate_columns(src, dst)

    # Step 3 - Enforce output CRS metadata when provided.
    ensure_crs(dst, crs_project)
    return str(dst)
