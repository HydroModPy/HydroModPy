"""Compatibility re-export for shared GeoParquet I/O helpers."""

from __future__ import annotations

from hydromodpy.core.io.geoparquet import (
    GEOPARQUET_SCHEMA_VERSION,
    GEOPARQUET_WRITE_DEFAULTS,
    read_geoparquet,
    write_geoparquet_atomic,
)

__all__ = [
    "GEOPARQUET_SCHEMA_VERSION",
    "GEOPARQUET_WRITE_DEFAULTS",
    "read_geoparquet",
    "write_geoparquet_atomic",
]
