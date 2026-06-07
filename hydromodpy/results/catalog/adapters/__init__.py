"""Concrete :class:`CatalogBackend` implementations.

``DuckDBBackend`` is the V1 adapter, backing every catalog opened from a
local workspace. Additional adapters can be plugged in by implementing
the :class:`~hydromodpy.results.catalog.ports.CatalogBackend` protocol.
"""

from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend

__all__ = ["DuckDBBackend"]
