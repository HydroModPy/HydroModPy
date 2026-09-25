"""Convert a DEM raster into HydroModPy domain surface objects.

Purpose
-------
Bridge geospatial raster metadata (transform, CRS, nodata) with HydroModPy
domain abstractions (``RasterSupport`` and ``Surface``).

Pipeline position
-----------------
Used once a DEM support is ready and must be injected into domain execution.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.surface import Surface


def build_surface_topo_from_dem(dem_path: str | Path) -> Surface:
    """Build a topographic ``Surface`` from one DEM file.

    The function reads the first DEM band, reconstructs georeferencing bounds
    from the affine transform, then builds a ``RasterSupport`` consumed by the
    domain ``Surface`` abstraction.
    """
    raster_path = Path(dem_path)
    if not raster_path.exists():
        raise FileNotFoundError(f"DEM not found: {raster_path}")
    return Surface.from_raster(raster_path, name="surface_topo")
