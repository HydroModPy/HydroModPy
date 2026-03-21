"""Data catalog package with lazy SQLAlchemy-backed catalog import."""

from __future__ import annotations

from hydromodpy.data_managers.registry.constants import (
    SENTINEL_CUSTOM,
    SENTINEL_EMPTY,
)

__all__ = ["DataCatalog", "SENTINEL_CUSTOM", "SENTINEL_EMPTY"]


def __getattr__(name: str):
    if name == "DataCatalog":
        from hydromodpy.data_managers.registry.catalog import DataCatalog

        return DataCatalog
    raise AttributeError(f"module 'hydromodpy.data_managers.registry' has no attribute {name!r}")
