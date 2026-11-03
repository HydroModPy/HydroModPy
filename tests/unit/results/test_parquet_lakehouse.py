"""Unit tests for the Parquet lakehouse.

Covers the atomic write path of a run store, the DuckDB view semantics of the
index, and the views after a run leaves the tree.
"""

from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.constants import PARQUET_VIEW_NAMES
from hydromodpy.results.catalog.indexer import index_new_runs, rebuild_index
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.trash import trash_run
from tests._helpers.run_stores import open_run_store


def _make_series(n: int = 5, start: str = "2020-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=n)
    return pd.Series([float(i) for i in range(n)], index=idx, name="head")


def _store(project: Path, name: str = "sim") -> RunStore:
    """Claim ``runs/<name>`` and open its store, without a field store."""
    return open_run_store(project, name, create_zarr=False)


def _seal_and_index(project: Path, store: RunStore) -> str:
    sid = store.sim_id
    seal_completed(store)
    rebuild_index(project)
    return sid


class TestAtomicWrite:
    def test_timeseries_written_to_parquet(self, tmp_path: Path):
        with _store(tmp_path) as store:
            sid = store.sim_id
            store.write_timeseries(sid, "P01", "head", _make_series(), unit="m")
            target = store.tables_dir_for(sid) / f"timeseries{PARQUET_FILE_SUFFIX}"
        assert target.is_file()
        assert not target.with_name(target.name + ".tmp").exists()

    def test_second_write_merges_without_losing_rows(self, tmp_path: Path):
        store = _store(tmp_path)
        store.write_timeseries(store.sim_id, "P01", "head", _make_series(), unit="m")
        store.write_timeseries(store.sim_id, "P02", "head", _make_series(), unit="m")
        sid = _seal_and_index(tmp_path, store)
        with Catalog(tmp_path) as cat:
            count = cat.connection.execute(
                "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", [sid]
            ).fetchone()[0]
        assert count == 10

    def test_rewrite_same_key_wins(self, tmp_path: Path):
        with _store(tmp_path) as store:
            sid = store.sim_id
            ts_first = _make_series(n=3)
            ts_second = pd.Series([100.0, 200.0, 300.0], index=ts_first.index, name="head")
            store.write_timeseries(sid, "P01", "head", ts_first, unit="m")
            store.write_timeseries(sid, "P01", "head", ts_second, unit="m")
            vals = store.query_timeseries(sid, "P01", "head").values.tolist()
        assert vals == [100.0, 200.0, 300.0]


class TestViewSemantics:
    def test_empty_view_has_expected_columns(self, tmp_path: Path):
        rebuild_index(tmp_path)
        with Catalog(tmp_path) as cat:
            for view in PARQUET_VIEW_NAMES:
                count = cat.connection.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
                assert count == 0
                cols = {
                    r[0]
                    for r in cat.connection.execute(f"DESCRIBE SELECT * FROM {view}").fetchall()
                }
                assert "sim_id" in cols

    def test_view_matches_run_facade(self, tmp_path: Path):
        store = _store(tmp_path)
        store.write_timeseries(store.sim_id, "P01", "head", _make_series(n=7), unit="m")
        sid = _seal_and_index(tmp_path, store)
        with Catalog(tmp_path) as cat:
            via_view = (
                cat.connection.execute(
                    "SELECT value FROM timeseries "
                    "WHERE sim_id = ? AND station_id = 'P01' AND variable = 'head' "
                    "ORDER BY timestep",
                    [sid],
                )
                .fetchdf()["value"]
                .tolist()
            )
            via_run = cat[sid].timeseries("head", station="P01").values.tolist()
        assert via_view == via_run


class TestTrash:
    def test_a_trashed_run_leaves_the_views(self, tmp_path: Path):
        store = _store(tmp_path)
        store.write_timeseries(store.sim_id, "P01", "head", _make_series(), unit="m")
        store.write_budgets(
            store.sim_id,
            [
                {
                    "timestep": 0,
                    "zone_id": "domain",
                    "component": "recharge",
                    "flux_in": 1.0,
                    "flux_out": 0.0,
                }
            ],
        )
        parquet_dir = store.tables_dir
        _seal_and_index(tmp_path, store)
        assert parquet_dir.is_dir()

        trash_run(tmp_path, "runs/sim", now=datetime(2026, 10, 15, tzinfo=UTC))
        index_new_runs(tmp_path)

        assert not parquet_dir.exists()
        with Catalog(tmp_path) as cat:
            remaining = cat.connection.execute("SELECT COUNT(*) FROM timeseries").fetchone()[0]
        assert remaining == 0


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


class TestAtomicInterruption:
    def test_no_tmp_file_visible_through_view(self, tmp_path: Path):
        """A ``.tmp`` file on disk must never be picked up by the view glob."""
        store = _store(tmp_path)
        store.write_timeseries(store.sim_id, "P01", "head", _make_series(), unit="m")
        stray = store.tables_dir / f"timeseries{PARQUET_FILE_SUFFIX}.tmp"
        sid = _seal_and_index(tmp_path, store)
        stray.write_bytes(b"corrupted")
        with Catalog(tmp_path) as cat:
            count = cat.connection.execute(
                "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", [sid]
            ).fetchone()[0]
        assert count == 5
