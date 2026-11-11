"""The reader reaches the index through the ``DuckDBBackend`` port, never through the raw cursor.

``Catalog`` owns a DuckDB connection and wraps it in a :class:`DuckDBBackend`
adapter; its reads go through the port so another adapter can take over
without a change outside the adapter. The port of a reader refuses writes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hydromodpy.core.exceptions import ReadOnlyError
from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run


@pytest.fixture
def catalog(tmp_path):
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    rebuild_index(root)
    with Catalog(root) as cat:
        yield cat


def test_the_reader_exposes_its_backend_as_the_port(catalog: Catalog) -> None:
    assert isinstance(catalog.backend, DuckDBBackend)
    assert isinstance(catalog.backend, DuckDBBackend)


def test_the_backend_of_a_reader_refuses_writes(catalog: Catalog) -> None:
    with pytest.raises(ReadOnlyError):
        catalog.backend.execute("DELETE FROM simulations")


def test_a_listing_goes_through_the_port(catalog: Catalog) -> None:
    real_backend = catalog.backend
    spy = MagicMock(wraps=real_backend, spec=DuckDBBackend)
    catalog._backend = spy
    try:
        frame = catalog.list_simulations()
    finally:
        catalog._backend = real_backend

    spy.query.assert_called()
    assert list(frame["name"]) == ["alpha"]
