"""Tests verifying that catalog mixins route through the CatalogBackend port.

The catalog facade owns both a raw DuckDB connection (``self._db``) and a
:class:`CatalogBackend` adapter (``self._backend``). V1 routes mixin writes
and reads through the port so a future Postgres adapter can take over
without code changes outside the adapter. These tests pin the contract.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend
from hydromodpy.results.catalog.ports import CatalogBackend


def _sim_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def catalog(tmp_path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def test_catalog_exposes_backend_as_protocol(catalog: SimulationCatalog) -> None:
    """The facade must expose a :class:`CatalogBackend` adapter."""
    assert isinstance(catalog._backend, CatalogBackend)
    assert isinstance(catalog._backend, DuckDBBackend)
    assert catalog.backend is catalog._backend


def test_write_metric_routes_insert_through_backend(catalog: SimulationCatalog) -> None:
    """``write_metric`` must dispatch its INSERT via ``_backend.execute``."""
    sid = _sim_id()
    catalog.register_simulation(
        sid,
        project="p",
        solver="modflow6",
        n_cells=1,
        n_layers=1,
        n_timesteps=1,
    )
    # Swap the backend with a mock that proxies real reads/upserts so the
    # rest of the catalog keeps working but execute() calls are tracked.
    real_backend = catalog._backend
    spy = MagicMock(wraps=real_backend, spec=CatalogBackend)
    catalog._backend = spy
    try:
        catalog.write_metric(sid, station_id="st1", metric_name="nse", value=0.42)
    finally:
        catalog._backend = real_backend

    # At least one execute() call carrying the INSERT INTO metrics SQL.
    insert_calls = [
        c
        for c in spy.execute.call_args_list
        if "INSERT INTO metrics" in (c.args[0] if c.args else "")
    ]
    assert insert_calls, "write_metric did not route INSERT through the backend port"
    # Round-trip via the real backend confirms the write landed.
    row = real_backend.fetch_one(
        "SELECT value FROM metrics WHERE sim_id = ? AND station_id = ?",
        [sid, "st1"],
    )
    assert row is not None
    assert row[0] == pytest.approx(0.42)


def test_list_simulations_routes_query_through_backend(catalog: SimulationCatalog) -> None:
    """A read accessor must use ``_backend.query`` rather than the raw cursor."""
    real_backend = catalog._backend
    spy = MagicMock(wraps=real_backend, spec=CatalogBackend)
    catalog._backend = spy
    try:
        df = catalog.list_simulations()
    finally:
        catalog._backend = real_backend
    spy.query.assert_called()
    assert df.empty  # no simulations registered in this test
