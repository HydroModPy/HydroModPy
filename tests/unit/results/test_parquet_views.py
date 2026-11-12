"""Parquet lakehouse of a run: the atomic write of a table, the DuckDB views of the index over the
tables of every run, and the views after a run leaves the tree.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from hydromodpy.results.catalog.constants import PARQUET_VIEW_NAMES
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import index_new_runs, rebuild_index
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.trash import trash_run
from tests._helpers.run_stores import open_run_store


def head_series(n=5):
    index = pd.date_range("2020-01-01", periods=n)
    return pd.Series([float(i) for i in range(n)], index=index, name="head")


def open_store(project):
    return open_run_store(project, "sim", create_zarr=False)


def seal_and_index(project, store):
    sim_id = store.sim_id
    seal_completed(store)
    rebuild_index(project)
    return sim_id


def count_rows(project, sql, *params):
    with Catalog(project) as catalog:
        return catalog.connection.execute(sql, list(params)).fetchone()[0]


def test_timeseries_written_to_parquet(tmp_path):
    with open_store(tmp_path) as store:
        store.write_timeseries(store.sim_id, "P01", "head", head_series(), unit="m")
        target = store.tables_dir_for(store.sim_id) / f"timeseries{PARQUET_FILE_SUFFIX}"
    assert target.is_file()
    assert not target.with_name(target.name + ".tmp").exists()


def test_second_write_merges_without_losing_rows(tmp_path):
    store = open_store(tmp_path)
    store.write_timeseries(store.sim_id, "P01", "head", head_series(), unit="m")
    store.write_timeseries(store.sim_id, "P02", "head", head_series(), unit="m")
    sim_id = seal_and_index(tmp_path, store)
    assert count_rows(tmp_path, "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", sim_id) == 10


def test_rewrite_same_key_wins(tmp_path):
    with open_store(tmp_path) as store:
        first = head_series(n=3)
        second = pd.Series([100.0, 200.0, 300.0], index=first.index, name="head")
        store.write_timeseries(store.sim_id, "P01", "head", first, unit="m")
        store.write_timeseries(store.sim_id, "P01", "head", second, unit="m")
        values = store.query_timeseries(store.sim_id, "P01", "head").values.tolist()
    assert values == [100.0, 200.0, 300.0]


def test_empty_view_has_expected_columns(tmp_path):
    rebuild_index(tmp_path)
    with Catalog(tmp_path) as catalog:
        for view in PARQUET_VIEW_NAMES:
            assert catalog.connection.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0] == 0
            described = catalog.connection.execute(f"DESCRIBE SELECT * FROM {view}").fetchall()
            assert "sim_id" in {row[0] for row in described}


def test_view_matches_run_facade(tmp_path):
    store = open_store(tmp_path)
    store.write_timeseries(store.sim_id, "P01", "head", head_series(n=7), unit="m")
    sim_id = seal_and_index(tmp_path, store)
    with Catalog(tmp_path) as catalog:
        via_view = (
            catalog.connection.execute(
                "SELECT value FROM timeseries "
                "WHERE sim_id = ? AND station_id = 'P01' AND variable = 'head' "
                "ORDER BY timestep",
                [sim_id],
            )
            .fetchdf()["value"]
            .tolist()
        )
        via_run = catalog[sim_id].timeseries("head", station="P01").values.tolist()
    assert via_view == via_run


def test_a_trashed_run_leaves_the_views(tmp_path):
    store = open_store(tmp_path)
    store.write_timeseries(store.sim_id, "P01", "head", head_series(), unit="m")
    budget_row = {
        "timestep": 0,
        "zone_id": "domain",
        "component": "recharge",
        "flux_in": 1.0,
        "flux_out": 0.0,
    }
    store.write_budgets(store.sim_id, [budget_row])
    parquet_dir = store.tables_dir
    seal_and_index(tmp_path, store)
    assert parquet_dir.is_dir()

    trash_run(tmp_path, "runs/sim", now=datetime(2026, 10, 15, tzinfo=UTC))
    index_new_runs(tmp_path)

    assert not parquet_dir.exists()
    assert count_rows(tmp_path, "SELECT COUNT(*) FROM timeseries") == 0


def test_a_tmp_file_is_not_in_the_view(tmp_path):
    # A file left by an interrupted write must never be picked up by the view glob.
    store = open_store(tmp_path)
    store.write_timeseries(store.sim_id, "P01", "head", head_series(), unit="m")
    stray = store.tables_dir / f"timeseries{PARQUET_FILE_SUFFIX}.tmp"
    sim_id = seal_and_index(tmp_path, store)
    stray.write_bytes(b"corrupted")
    assert count_rows(tmp_path, "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", sim_id) == 5
