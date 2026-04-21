"""Low-level I/O helpers: raster, vector, CRS, JSON, HTTP.

Submodules
----------
raster_io       GeoTIFF / NetCDF loading, clipping, reprojection, export.
vector_io       Shapefile / GeoPackage helpers.
crs             pyproj CRS helpers (UTM detection, transform, bootstrap).
canonical_json  Deterministic JSON dump (stable key ordering, sorted sets).
http_client     HTTP client with retry / backoff / timeout. Scaffold — filled in G04.
"""

from __future__ import annotations

from hydromodpy.core.io.canonical_json import dumps as json_dumps
from hydromodpy.core.io.canonical_json import loads as json_loads

__all__ = ["json_dumps", "json_loads"]
