"""The media types a job document names, spelled once.

One artefact carries its media type in three places: the capability
declaration, the output record of ``outcome.json`` and the artefact record of
``manifest.json``. Three literals would be three chances to write
``image/tiff;application=geotiff`` without the space, and an orchestrator
filtering on the type would then miss the file it asked for.

These are the IANA names, with the parameter spelling the OGC process
description uses. Nothing here is a file extension table: a capability
declares the type of what it writes, it does not guess it from a suffix.
"""

from __future__ import annotations

JSON_MEDIA_TYPE = "application/json"
GEOJSON_MEDIA_TYPE = "application/geo+json"
GEOPACKAGE_MEDIA_TYPE = "application/geopackage+sqlite3"
GEOTIFF_MEDIA_TYPE = "image/tiff; application=geotiff"
NETCDF_MEDIA_TYPE = "application/netcdf"
PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"

__all__ = [
    "GEOJSON_MEDIA_TYPE",
    "GEOPACKAGE_MEDIA_TYPE",
    "GEOTIFF_MEDIA_TYPE",
    "JSON_MEDIA_TYPE",
    "NETCDF_MEDIA_TYPE",
    "PARQUET_MEDIA_TYPE",
]
