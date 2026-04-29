"""Unit tests for the Parquet lakehouse refactor.

Covers the atomic write path, the DuckDB view semantics, and the ``.hmp``
package round-trip.
"""

from __future__ import annotations

import multiprocessing
import uuid
from pathlib import Path

import pandas as pd

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.catalog_schema import PARQUET_VIEW_NAMES


def _make_series(n: int = 5, start: str = "2020-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=n)
    return pd.Series([float(i) for i in range(n)], index=idx, name="head")


def _register(catalog: SimulationCatalog, name: str = "sim") -> str:
    sid = str(uuid.uuid4())
    catalog.register_simulation(sid, project="p", solver="modflow6", name=name)
    return sid


class TestAtomicWrite:
    def test_timeseries_written_to_parquet(self, tmp_path: Path):
        with SimulationCatalog(tmp_path) as cat:
            sid = _register(cat)
            cat.write_timeseries(sid, "P01", "head", _make_series(), unit="m")
            target = cat.parquet_dir_for(sid) / "timeseries.parquet"
        assert target.is_file()
        assert not target.with_name(target.name + ".tmp").exists()

    def test_second_write_merges_without_losing_rows(self, tmp_path: Path):
        with SimulationCatalog(tmp_path) as cat:
            sid = _register(cat)
            cat.write_timeseries(sid, "P01", "head", _make_series(), unit="m")
            cat.write_timeseries(sid, "P02", "head", _make_series(), unit="m")
            count = cat._connection.execute(
                "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", [sid]
            ).fetchone()[0]
        assert count == 10

    def test_rewrite_same_key_wins(self, tmp_path: Path):
        with SimulationCatalog(tmp_path) as cat:
            sid = _register(cat)
            ts_first = _make_series(n=3)
            ts_second = pd.Series([100.0, 200.0, 300.0], index=ts_first.index, name="head")
            cat.write_timeseries(sid, "P01", "head", ts_first, unit="m")
            cat.write_timeseries(sid, "P01", "head", ts_second, unit="m")
            vals = cat.query_timeseries(sid, "P01", "head").values.tolist()
        assert vals == [100.0, 200.0, 300.0]


class TestViewSemantics:
    def test_empty_view_has_expected_columns(self, tmp_path: Path):
        with SimulationCatalog(tmp_path) as cat:
            for view in PARQUET_VIEW_NAMES:
                count = cat._connection.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
                assert count == 0
                cols = {
                    r[0]
                    for r in cat._connection.execute(f"DESCRIBE SELECT * FROM {view}").fetchall()
                }
                assert "sim_id" in cols

    def test_view_matches_run_facade(self, tmp_path: Path):
        with SimulationCatalog(tmp_path) as cat:
            sid = _register(cat)
            ts = _make_series(n=7)
            cat.write_timeseries(sid, "P01", "head", ts, unit="m")
            via_view = (
                cat._connection.execute(
                    "SELECT value FROM timeseries "
                    "WHERE sim_id = ? AND station_id = 'P01' AND variable = 'head' "
                    "ORDER BY datetime",
                    [sid],
                )
                .fetchdf()["value"]
                .tolist()
            )
            via_run = cat[sid].timeseries("head", station="P01").values.tolist()
        assert via_view == via_run


class TestDelete:
    def test_delete_removes_parquet_dir(self, tmp_path: Path):
        with SimulationCatalog(tmp_path) as cat:
            sid = _register(cat)
            cat.write_timeseries(sid, "P01", "head", _make_series(), unit="m")
            cat.write_budgets(
                sid,
                [
                    {
                        "timestep": 0,
                        "zone_id": "0",
                        "component": "recharge",
                        "flux_in": 1.0,
                        "flux_out": 0.0,
                    }
                ],
            )
            parquet_dir = cat.parquet_dir_for(sid)
            assert parquet_dir.is_dir()
            cat.delete(sid)
            assert not parquet_dir.exists()
            remaining = cat._connection.execute("SELECT COUNT(*) FROM timeseries").fetchone()[0]
        assert remaining == 0


def _worker_write(args: tuple) -> str:
    workspace, sim_label = args
    with SimulationCatalog(Path(workspace)) as cat:
        sid = str(uuid.uuid4())
        cat.register_simulation(sid, project="p", solver="modflow6", name=sim_label)
        cat.write_timeseries(
            sid,
            "P01",
            "head",
            _make_series(n=5),
            unit="m",
        )
        return sid


class TestConcurrentWrites:
    def test_eight_parallel_workers_dont_lose_data(self, tmp_path: Path):
        # Initialise the workspace so child processes don't race on scaffold.
        with SimulationCatalog(tmp_path) as cat:
            _ = cat
        inputs = [(tmp_path, f"sim_{i}") for i in range(8)]
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=4) as pool:
            sim_ids = pool.map(_worker_write, inputs)
        assert len(set(sim_ids)) == 8
        with SimulationCatalog(tmp_path) as cat:
            total = cat._connection.execute("SELECT COUNT(*) FROM timeseries").fetchone()[0]
            sims = cat._connection.execute(
                "SELECT COUNT(DISTINCT sim_id) FROM timeseries"
            ).fetchone()[0]
        assert sims == 8
        assert total == 8 * 5


class TestAtomicInterruption:
    def test_no_tmp_file_visible_through_view(self, tmp_path: Path):
        """A ``.tmp`` file on disk must never be picked up by the view glob."""
        with SimulationCatalog(tmp_path) as cat:
            sid = _register(cat)
            cat.write_timeseries(sid, "P01", "head", _make_series(), unit="m")
            stray = cat.parquet_dir_for(sid) / "timeseries.parquet.tmp"
            stray.write_bytes(b"corrupted")
            count = cat._connection.execute(
                "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", [sid]
            ).fetchone()[0]
            assert count == 5
            stray.unlink()
