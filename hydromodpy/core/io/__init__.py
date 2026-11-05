"""Low-level I/O helpers: raster, vector, CRS, JSON, HTTP.

Submodules
----------
raster_io       GeoTIFF / NetCDF loading, masking, reprojection, export.
vector_io       Shapefile / GeoPackage helpers.
crs             pyproj CRS helpers (UTM detection, transform, bootstrap).
canonical_json  Deterministic JSON dump (stable key ordering, sorted sets).
http_client     HTTP client with retry / backoff / timeout / SHA-256 streaming.
pinned_download Fetch a file whose SHA-256 the package pins, and refuse other bytes.
"""
