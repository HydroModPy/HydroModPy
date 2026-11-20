"""Parallel workers that write Parquet tables into one project lose no row."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pandas as pd

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


def _make_series(n: int = 5, start: str = "2020-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=n)
    return pd.Series([float(i) for i in range(n)], index=idx, name="head")


def _worker_write(args: tuple) -> str:
    workspace, sim_label = args
    store = open_run_store(Path(workspace), sim_label, create_zarr=False)
    sid = store.sim_id
    store.write_timeseries(sid, "P01", "head", _make_series(n=5), unit="m")
    seal_completed(store)
    return sid


class TestConcurrentWrites:
    def test_eight_parallel_workers_dont_lose_data(self, tmp_path: Path):
        inputs = [(tmp_path, f"sim_{i}") for i in range(8)]
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=4) as pool:
            sim_ids = pool.map(_worker_write, inputs)
        assert len(set(sim_ids)) == 8
        rebuild_index(tmp_path)
        with Catalog(tmp_path) as cat:
            total = cat.connection.execute("SELECT COUNT(*) FROM timeseries").fetchone()[0]
            sims = cat.connection.execute(
                "SELECT COUNT(DISTINCT sim_id) FROM timeseries"
            ).fetchone()[0]
        assert sims == 8
        assert total == 8 * 5
