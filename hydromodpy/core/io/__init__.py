"""Low-level I/O helpers: raster, vector, CRS, JSON, HTTP.

Submodules
----------
raster_io       GeoTIFF / NetCDF loading, masking, reprojection, export.
vector_io       Shapefile / GeoPackage helpers.
crs             pyproj CRS helpers (UTM detection, transform, bootstrap).
canonical_json  Deterministic JSON dump (stable key ordering, sorted sets).
fetch           The one HTTP client, made for each call with its bounds: an
                allowed-host set, no private address unless the host is named,
                a byte ceiling, redirects followed by hand, and sha256 pinning.
"""
