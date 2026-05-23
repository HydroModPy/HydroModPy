"""Parquet write/scan baseline benchmarks.

Covers pyarrow zstd write (50_000 rows, single row group) and a polars
lazy scan with predicate pushdown.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

pytestmark = pytest.mark.performance
pl = pytest.importorskip("polars")


def _build_table(n_rows: int) -> pa.Table:
    """Return a pyarrow Table with id INT64, ts TIMESTAMP, val DOUBLE."""
    rng = np.random.default_rng(seed=42)
    ids = np.arange(n_rows, dtype=np.int64)
    base = np.datetime64("2026-01-01T00:00:00", "us")
    ts = base + np.arange(n_rows, dtype="int64") * np.timedelta64(1, "s")
    val = rng.random(n_rows, dtype=np.float64)
    return pa.table(
        {
            "id": pa.array(ids, type=pa.int64()),
            "ts": pa.array(ts, type=pa.timestamp("us")),
            "val": pa.array(val, type=pa.float64()),
        }
    )


@pytest.fixture(scope="function")
def parquet_table() -> pa.Table:
    """Build a 50_000 row pyarrow Table once per benchmark function."""
    return _build_table(n_rows=50_000)


@pytest.fixture(scope="function")
def parquet_path(tmp_path: Path, parquet_table: pa.Table) -> Path:
    """Write a 50_000 row Parquet file with zstd + 1 row group."""
    path = tmp_path / "data.parquet"
    pq.write_table(
        parquet_table,
        str(path),
        compression="zstd",
        row_group_size=50_000,
    )
    return path


@pytest.mark.benchmark(group="parquet")
def test_parquet_write_atomic(benchmark, tmp_path: Path, parquet_table: pa.Table) -> None:
    """Write 50_000 rows to Parquet with zstd + 50_000-row group."""
    out = tmp_path / "out.parquet"

    def _write() -> None:
        pq.write_table(
            parquet_table,
            str(out),
            compression="zstd",
            row_group_size=50_000,
        )

    benchmark(_write)


@pytest.mark.benchmark(group="parquet")
def test_parquet_scan_polars(benchmark, parquet_path: Path) -> None:
    """Scan + filter the 50_000-row Parquet via polars lazy."""

    def _scan() -> int:
        return pl.scan_parquet(parquet_path).filter(pl.col("val") > 0.5).collect().height

    benchmark(_scan)
