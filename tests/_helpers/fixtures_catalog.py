"""Catalog fixtures for the test suite.

Provides a :class:`~hydromodpy.results.catalog.Catalog` factory
that opens DuckDB-backed catalogs for unit, integration and e2e coverage.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from hydromodpy.results.catalog import Catalog


@contextmanager
def simulation_catalog(root: Path) -> Iterator[Catalog]:
    """Open a Catalog and close it after the test."""
    cat = Catalog(root)
    try:
        yield cat
    finally:
        cat.close()
