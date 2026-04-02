"""Data catalog package backed by DuckDB."""

from __future__ import annotations

from hydromodpy.data.registry.constants import (
    SENTINEL_CUSTOM,
    SENTINEL_EMPTY,
)

__all__ = ["DataCatalogDuckDB", "DataCatalog", "SENTINEL_CUSTOM", "SENTINEL_EMPTY"]


def __getattr__(name: str):
    if name in ("DataCatalog", "DataCatalogDuckDB"):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

        return DataCatalogDuckDB
    raise AttributeError(f"module 'hydromodpy.data.registry' has no attribute {name!r}")
