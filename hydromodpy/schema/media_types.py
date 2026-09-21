"""The media types a job document names, spelled once.

One artefact carries its media type in three places: the capability
declaration, the output record of ``outcome.json`` and the artefact record of
``manifest.json``. Three literals would be three chances to write
``image/tiff;application=geotiff`` without the space, and an orchestrator
filtering on the type would then miss the file it asked for.

Most of these are registered IANA names, with the parameter spelling the OGC
process description uses. ``ZARR_MEDIA_TYPE`` and ``TOML_MEDIA_TYPE`` are not
IANA-registered; they spell the ``application/x.zarr-store`` and
``application/toml`` strings this codebase already writes to disk, kept here
so every writer of those two formats agrees on one spelling. Nothing here is
a file extension table: a capability declares the type of what it writes, it
does not guess it from a suffix. This table does not cover media types owned
by something outside this codebase's control, such as an HTTP server's own
``Content-Type`` header or a third-party API's ``Accept`` header.
"""

from __future__ import annotations

JSON_MEDIA_TYPE = "application/json"
GEOJSON_MEDIA_TYPE = "application/geo+json"
GEOPACKAGE_MEDIA_TYPE = "application/geopackage+sqlite3"
GEOTIFF_MEDIA_TYPE = "image/tiff; application=geotiff"
NETCDF_MEDIA_TYPE = "application/netcdf"
OCTET_STREAM_MEDIA_TYPE = "application/octet-stream"
PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
TOML_MEDIA_TYPE = "application/toml"
ZARR_MEDIA_TYPE = "application/x.zarr-store"

__all__ = [
    "GEOJSON_MEDIA_TYPE",
    "GEOPACKAGE_MEDIA_TYPE",
    "GEOTIFF_MEDIA_TYPE",
    "JSON_MEDIA_TYPE",
    "NETCDF_MEDIA_TYPE",
    "OCTET_STREAM_MEDIA_TYPE",
    "PARQUET_MEDIA_TYPE",
    "TOML_MEDIA_TYPE",
    "ZARR_MEDIA_TYPE",
]
