"""Data catalog package backed by DuckDB."""

from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec

from hydromodpy.data.registry.constants import (
    SENTINEL_CUSTOM,
    SENTINEL_EMPTY,
)

__all__ = [
    "DataCatalogDuckDB",
    "SENTINEL_CUSTOM",
    "SENTINEL_EMPTY",
]


def __getattr__(name: str):
    if name == "DataCatalogDuckDB":
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

        globals()[name] = DataCatalogDuckDB
        return DataCatalogDuckDB
    module_name = f"{__name__}.{name}"
    if find_spec(module_name) is not None:
        module = import_module(module_name)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
