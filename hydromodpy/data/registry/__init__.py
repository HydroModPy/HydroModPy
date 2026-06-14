"""Data catalog package backed by DuckDB."""

from __future__ import annotations

from hydromodpy.data.registry.constants import (
    SENTINEL_CUSTOM,
    SENTINEL_EMPTY,
)

__all__ = [
    "DataCatalogDuckDB",
    "DuckDBCacheBackend",
    "SENTINEL_CUSTOM",
    "SENTINEL_EMPTY",
]


def __getattr__(name: str):
    if name == "DataCatalogDuckDB":
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

        return DataCatalogDuckDB
    if name == "DuckDBCacheBackend":
        # Public re-export so other packages (e.g. the CLI gc/vacuum worker) do
        # not reach into the private ``_backend`` module across package lines.
        from hydromodpy.data.registry._backend import DuckDBCacheBackend

        return DuckDBCacheBackend
    raise AttributeError(f"module 'hydromodpy.data.registry' has no attribute {name!r}")
