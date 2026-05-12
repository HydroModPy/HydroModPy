"""Tests for the v2.x-ready :class:`PostgresBackend` stub.

The stub is shipped in v2.0 so dependent code can already wire a backend
selection point. Every method raises ``NotImplementedError`` with a stable
message that the test suite pins.
"""

from __future__ import annotations

import pytest

from hydromodpy.results.catalog.adapters.postgres import PostgresBackend
from hydromodpy.results.catalog.ports import CatalogBackend

_STUB_MESSAGE = "Postgres backend ready-to-go in v2.x, not implemented in v2.0"


@pytest.fixture
def stub() -> PostgresBackend:
    return PostgresBackend("postgresql://user:pass@host/db")


def test_postgres_is_catalog_backend_protocol(stub: PostgresBackend) -> None:
    assert isinstance(stub, CatalogBackend)


def test_dsn_round_trips(stub: PostgresBackend) -> None:
    assert stub.dsn == "postgresql://user:pass@host/db"


def test_ensure_schema_raises(stub: PostgresBackend) -> None:
    with pytest.raises(NotImplementedError) as exc:
        stub.ensure_schema()
    assert _STUB_MESSAGE in str(exc.value)


def test_query_raises(stub: PostgresBackend) -> None:
    with pytest.raises(NotImplementedError) as exc:
        stub.query("SELECT 1")
    assert _STUB_MESSAGE in str(exc.value)


def test_execute_raises(stub: PostgresBackend) -> None:
    with pytest.raises(NotImplementedError) as exc:
        stub.execute("CREATE TABLE t (a INT)")
    assert _STUB_MESSAGE in str(exc.value)


def test_fetch_one_raises(stub: PostgresBackend) -> None:
    with pytest.raises(NotImplementedError) as exc:
        stub.fetch_one("SELECT 1")
    assert _STUB_MESSAGE in str(exc.value)


def test_fetch_all_raises(stub: PostgresBackend) -> None:
    with pytest.raises(NotImplementedError) as exc:
        stub.fetch_all("SELECT 1")
    assert _STUB_MESSAGE in str(exc.value)


def test_insert_raises(stub: PostgresBackend) -> None:
    with pytest.raises(NotImplementedError) as exc:
        stub.insert("t", {"a": 1})
    assert _STUB_MESSAGE in str(exc.value)


def test_upsert_raises(stub: PostgresBackend) -> None:
    with pytest.raises(NotImplementedError) as exc:
        stub.upsert("t", {"a": 1, "b": 2}, key_cols=["a"])
    assert _STUB_MESSAGE in str(exc.value)


def test_transaction_raises(stub: PostgresBackend) -> None:
    with pytest.raises(NotImplementedError) as exc:
        stub.transaction()
    assert _STUB_MESSAGE in str(exc.value)


def test_close_is_noop(stub: PostgresBackend) -> None:
    # Close on the stub must be safe to call repeatedly.
    stub.close()
    stub.close()
