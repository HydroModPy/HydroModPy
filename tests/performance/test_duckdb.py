"""DuckDB cold-open and simple-query baseline benchmarks.

Self-contained fixtures: no hydromodpy runtime dependency. The schema is
``simulations(sim_id UUID, name VARCHAR, value DOUBLE)``, sized at 1000
rows, which mimics the smallest catalog row shape used in v2.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
import uuid_utils

pytestmark = pytest.mark.performance


def _populate_simulations(path: Path, n_rows: int) -> None:
    """Create a simulations table with *n_rows* synthetic rows."""
    rows = [(str(uuid_utils.uuid7()), f"sim_{i}", float(i) * 0.1) for i in range(n_rows)]
    con = duckdb.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE simulations (sim_id UUID, name VARCHAR, value DOUBLE)",
        )
        con.executemany("INSERT INTO simulations VALUES (?, ?, ?)", rows)
        con.execute("CHECKPOINT")
    finally:
        con.close()


@pytest.fixture(scope="function")
def duckdb_path(tmp_path: Path) -> Path:
    """Build a populated DuckDB file with 1000 simulations rows."""
    db_path = tmp_path / "catalog.duckdb"
    _populate_simulations(db_path, n_rows=1000)
    return db_path


@pytest.mark.benchmark(group="duckdb")
def test_duckdb_open_cold(benchmark, duckdb_path: Path) -> None:
    """Cold connect to a DuckDB file (~1000 rows)."""

    def _connect() -> None:
        con = duckdb.connect(str(duckdb_path))
        con.close()

    benchmark(_connect)


@pytest.mark.benchmark(group="duckdb")
def test_duckdb_query_simple(benchmark, duckdb_path: Path) -> None:
    """SELECT with a value predicate over 1000 rows on an open connection."""
    con = duckdb.connect(str(duckdb_path))
    try:

        def _query() -> int:
            return (
                con.execute(
                    "SELECT sim_id, name, value FROM simulations WHERE value > ?",
                    [50.0],
                )
                .fetchall()
                .__len__()
            )

        benchmark(_query)
    finally:
        con.close()
