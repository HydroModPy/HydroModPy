"""The reader reaches the index through the ``DuckDBBackend`` port, never through the raw cursor.

``Catalog`` owns a DuckDB connection and wraps it in a :class:`DuckDBBackend`
adapter; its reads go through the port so another adapter can take over
without a change outside the adapter. The port of a reader refuses writes.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ReadOnlyError
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


def test_the_backend_of_a_reader_refuses_writes(catalog: Catalog) -> None:
    with pytest.raises(ReadOnlyError):
        catalog.backend.execute("DELETE FROM simulations")
