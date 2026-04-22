"""Unit tests for the Parquet lakehouse refactor.

Covers the atomic write path, the DuckDB view semantics, the ``.hmp``
package round-trip, and the ``hmp migrate`` command.
"""

from __future__ import annotations

import argparse
import multiprocessing
import uuid
from pathlib import Path

import duckdb
import pandas as pd

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.catalog_schema import (
    PARQUET_VIEW_NAMES,
    ensure_parquet_views,
    ensure_schema,
)


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
        target = tmp_path / "simulations" / f"{sid}.parquet" / "timeseries.parquet"
        assert target.is_file()
        assert not target.with_name(target.name + ".tmp").exists()

    def test_second_write_merges_without_losing_rows(self, tmp_path: Path):
        with SimulationCatalog(tmp_path) as cat:
            sid = _register(cat)
            cat.write_timeseries(sid, "P01", "head", _make_series(), unit="m")
            cat.write_timeseries(sid, "P02", "head", _make_series(), unit="m")
            count = cat.connection.execute(
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
                count = cat.connection.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
                assert count == 0
                cols = {
                    r[0]
                    for r in cat.connection.execute(f"DESCRIBE SELECT * FROM {view}").fetchall()
                }
                assert "sim_id" in cols

    def test_view_matches_run_facade(self, tmp_path: Path):
        with SimulationCatalog(tmp_path) as cat:
            sid = _register(cat)
            ts = _make_series(n=7)
            cat.write_timeseries(sid, "P01", "head", ts, unit="m")
            via_view = (
                cat.connection.execute(
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
            parquet_dir = tmp_path / "simulations" / f"{sid}.parquet"
            assert parquet_dir.is_dir()
            cat.delete(sid)
            assert not parquet_dir.exists()
            remaining = cat.connection.execute("SELECT COUNT(*) FROM timeseries").fetchone()[0]
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
            total = cat.connection.execute("SELECT COUNT(*) FROM timeseries").fetchone()[0]
            sims = cat.connection.execute(
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
            stray = tmp_path / "simulations" / f"{sid}.parquet" / "timeseries.parquet.tmp"
            stray.write_bytes(b"corrupted")
            count = cat.connection.execute(
                "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", [sid]
            ).fetchone()[0]
            assert count == 5
            stray.unlink()


class TestMigration:
    def _build_legacy_catalog(self, workspace: Path) -> str:
        """Recreate a pre-refactor catalog by re-introducing the old tables."""
        workspace.mkdir(parents=True, exist_ok=True)
        db = duckdb.connect(str(workspace / "hydromodpy.duckdb"))
        try:
            ensure_schema(db)
            db.execute(
                "CREATE TABLE IF NOT EXISTS timeseries ("
                "sim_id UUID NOT NULL, station_id VARCHAR, variable VARCHAR, "
                "datetime TIMESTAMPTZ, value DOUBLE, unit VARCHAR, "
                "qflag VARCHAR DEFAULT 'simulated')"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS budgets ("
                "sim_id UUID NOT NULL, timestep INTEGER, zone_id VARCHAR, "
                "component VARCHAR, flux_in DOUBLE, flux_out DOUBLE, "
                "unit VARCHAR)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS mass_balance ("
                "sim_id UUID NOT NULL, timestep INTEGER, total_in DOUBLE, "
                "total_out DOUBLE, storage_in DOUBLE, storage_out DOUBLE, "
                "percent_error DOUBLE, unit VARCHAR)"
            )
            sid = str(uuid.uuid4())
            db.execute(
                "INSERT INTO simulations (sim_id, project, solver) VALUES (?, 'p', 'modflow6')",
                [sid],
            )
            for i in range(3):
                db.execute(
                    "INSERT INTO timeseries (sim_id, station_id, variable, "
                    "datetime, value, unit, qflag) "
                    "VALUES (?, 'P01', 'head', TIMESTAMPTZ '2020-01-0"
                    + str(i + 1)
                    + " 00:00:00+00', ?, 'm', 'simulated')",
                    [sid, float(i)],
                )
            db.execute(
                "INSERT INTO budgets (sim_id, timestep, zone_id, component, "
                "flux_in, flux_out, unit) VALUES (?, 0, '0', 'recharge', 1.0, 0.0, 'm3/d')",
                [sid],
            )
            db.execute(
                "INSERT INTO mass_balance (sim_id, timestep, total_in, "
                "total_out, storage_in, storage_out, percent_error, unit) "
                "VALUES (?, 0, 1.0, 0.95, 0.0, 0.0, 0.5, 'm3/d')",
                [sid],
            )
        finally:
            db.close()
        return sid

    def test_migrate_moves_rows_and_drops_tables(self, tmp_path: Path):
        workspace = tmp_path / "ws"
        sid = self._build_legacy_catalog(workspace)
        from hydromodpy._cli.commands import migrate as migrate_cmd

        args = migrate_cmd.register(argparse_stub()).parse_args(["--workspace", str(workspace)])
        migrate_cmd.run(args)

        # Views must return the migrated rows.
        with SimulationCatalog(workspace) as cat:
            ts = (
                cat.connection.execute(
                    "SELECT value FROM timeseries WHERE sim_id = ? ORDER BY datetime",
                    [sid],
                )
                .fetchdf()["value"]
                .tolist()
            )
            assert ts == [0.0, 1.0, 2.0]
            assert cat.connection.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 1
            assert cat.connection.execute("SELECT COUNT(*) FROM mass_balance").fetchone()[0] == 1
            # Parquet files must exist on disk.
            for view in PARQUET_VIEW_NAMES:
                assert (workspace / "simulations" / f"{sid}.parquet" / f"{view}.parquet").is_file()
            # Legacy tables must be gone.
            tables = {
                r[0]
                for r in cat.connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='main' AND table_type='BASE TABLE'"
                ).fetchall()
            }
            assert "timeseries" not in tables
            assert "budgets" not in tables
            assert "mass_balance" not in tables

    def test_migrate_is_idempotent(self, tmp_path: Path):
        workspace = tmp_path / "ws"
        self._build_legacy_catalog(workspace)
        from hydromodpy._cli.commands import migrate as migrate_cmd

        parser = migrate_cmd.register(argparse_stub())
        migrate_cmd.run(parser.parse_args(["--workspace", str(workspace)]))
        # Second run should be a no-op and not raise.
        migrate_cmd.run(parser.parse_args(["--workspace", str(workspace)]))


class _Subparsers:
    """Minimal stub providing the ``add_parser`` interface."""

    def __init__(self) -> None:
        import argparse as _argparse

        self._parser = _argparse.ArgumentParser()
        self._sub = self._parser.add_subparsers()

    def add_parser(self, name: str, help: str = "") -> argparse.ArgumentParser:
        return self._sub.add_parser(name, help=help)


def argparse_stub():
    """Return an object the ``register(subparsers)`` callable accepts."""
    import argparse as _argparse

    parser = _argparse.ArgumentParser()
    return parser.add_subparsers()


# ``argparse_stub`` above returns a ``_SubParsersAction`` which has the
# ``add_parser`` method that ``register`` needs; we keep the helper and
# expose it so the migration tests stay readable.
