"""Concrete :class:`CatalogBackend` implementations.

``DuckDBBackend`` is the production v2.0 adapter. ``PostgresBackend`` is a
ready-to-go stub that satisfies the Protocol structurally and raises
``NotImplementedError`` on every call. It is kept in v2.0 so calling code
can already depend on a stable Postgres entry point.
"""

from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend
from hydromodpy.results.catalog.adapters.postgres import PostgresBackend

__all__ = ["DuckDBBackend", "PostgresBackend"]
