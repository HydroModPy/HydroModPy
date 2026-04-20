"""Unit tests for the refactored DuckDB simulation catalog (phase P02)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import duckdb
import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.catalog_schema import (
    TABLE_NAMES,
    ensure_schema,
)


@pytest.fixture
def mem_conn():
    conn = duckdb.connect(":memory:")
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def catalog(tmp_path: Path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def _sim_id() -> str:
    return str(uuid.uuid4())


class TestSchema:
    def test_twelve_tables_present(self, mem_conn):
        rows = mem_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main'"
        ).fetchall()
        tables = {r[0] for r in rows}
        assert set(TABLE_NAMES) <= tables
        assert len(TABLE_NAMES) == 12

    def test_schema_version_table_absent(self, mem_conn):
        rows = mem_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main'"
        ).fetchall()
        tables = {r[0] for r in rows}
        assert "_schema_version" not in tables

    def test_config_snapshot_column_exists(self, mem_conn):
        row = mem_conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='simulations' AND column_name='config_snapshot'"
        ).fetchone()
        assert row is not None
        assert "JSON" in row[0].upper()

    def test_geographic_fingerprint_column_exists(self, mem_conn):
        row = mem_conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='simulations' "
            "AND column_name='geographic_fingerprint'"
        ).fetchone()
        assert row is not None
        assert "VARCHAR" in row[0].upper()

    def test_bbox_expanded_to_four_columns(self, mem_conn):
        cols = {
            r[0]
            for r in mem_conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='simulations'"
            ).fetchall()
        }
        assert {"bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax"} <= cols
        assert "bbox" not in cols  # old single-array column is gone

    def test_period_columns_timestamptz(self, mem_conn):
        rows = mem_conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name='simulations' "
            "AND column_name IN ('period_start','period_end',"
            "                    'started_at','ended_at','created_at')"
        ).fetchall()
        for _, dtype in rows:
            assert "TIME" in dtype.upper()

    def test_ensure_schema_is_idempotent(self, mem_conn):
        ensure_schema(mem_conn)
        ensure_schema(mem_conn)
        rows = mem_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main'"
        ).fetchall()
        tables = {r[0] for r in rows}
        assert set(TABLE_NAMES) <= tables


class TestRegisterAndRead:
    def test_register_creates_row(self, catalog):
        sid = _sim_id()
        catalog.register_simulation(sid, project="p1", solver="modflow6")
        row = catalog.connection.execute(
            "SELECT project, solver, status FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()
        assert row == ("p1", "modflow6", "running")

    def test_register_stores_config_snapshot(self, catalog):
        sid = _sim_id()
        snapshot = {"flow": {"regime": "steady"}, "k": 1.5e-5}
        catalog.register_simulation(
            sid, project="p", solver="modflow6",
            config_snapshot=snapshot,
        )
        raw = catalog.connection.execute(
            "SELECT config_snapshot FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()[0]
        assert json.loads(raw) == snapshot

    def test_register_config_snapshot_falls_back_to_config(self, catalog):
        sid = _sim_id()
        config = {"a": 1, "b": 2}
        catalog.register_simulation(
            sid, project="p", solver="modflow6", config=config,
        )
        raw = catalog.connection.execute(
            "SELECT config_snapshot FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()[0]
        assert json.loads(raw) == config

    def test_register_maps_bbox_and_crs(self, catalog):
        sid = _sim_id()
        catalog.register_simulation(
            sid, project="p", solver="modflow6",
            bbox=[1.0, 2.0, 3.0, 4.0], crs="EPSG:2154",
        )
        row = catalog.connection.execute(
            "SELECT bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax, "
            "       crs_wkt, crs_epsg "
            "FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()
        assert row == (1.0, 2.0, 3.0, 4.0, "EPSG:2154", 2154)

    def test_register_persists_geographic_fingerprint(self, catalog):
        sid = _sim_id()
        fp = "a" * 64
        catalog.register_simulation(
            sid, project="p", solver="modflow6",
            geographic_fingerprint=fp,
        )
        row = catalog.connection.execute(
            "SELECT geographic_fingerprint FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()
        assert row[0] == fp

    def test_register_with_zarr_creates_store(self, catalog):
        sid = _sim_id()
        sz = catalog.register_simulation(
            sid, project="p", solver="modflow6",
            n_cells=16, n_layers=2, geographic_fingerprint="fp-abc",
        )
        try:
            assert sz is not None
            assert sz.geographic_fingerprint == "fp-abc"
            zarr_dir = catalog.workspace_path / "simulations" / f"{sid}.zarr"
            assert zarr_dir.is_dir()
        finally:
            if sz is not None:
                sz.close()


class TestPrimaryKeys:
    def test_parameters_pk_rejects_duplicates(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO parameters (sim_id, param_name, value) "
            "VALUES (?, 'K', 1.0)", [sid],
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO parameters (sim_id, param_name, value) "
                "VALUES (?, 'K', 2.0)", [sid],
            )

    def test_metrics_pk_includes_variable(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO metrics (sim_id, station_id, variable, "
            "metric_name, value) "
            "VALUES (?, 'P01', 'head', 'nse', 0.8)", [sid],
        )
        # Same metric / variable / station → conflict
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO metrics (sim_id, station_id, variable, "
                "metric_name, value) "
                "VALUES (?, 'P01', 'head', 'nse', 0.9)", [sid],
            )
        # Different variable → distinct row allowed
        mem_conn.execute(
            "INSERT INTO metrics (sim_id, station_id, variable, "
            "metric_name, value) "
            "VALUES (?, 'P01', 'discharge', 'nse', 0.7)", [sid],
        )


class TestForeignKeys:
    def test_parameters_rejects_unknown_sim(self, mem_conn):
        unknown = _sim_id()
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO parameters (sim_id, param_name, value) "
                "VALUES (?, 'K', 1.0)", [unknown],
            )


class TestChecks:
    def test_status_enum_enforced(self, mem_conn):
        sid = _sim_id()
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO simulations (sim_id, project, solver, status) "
                "VALUES (?, 'p', 'mf6', 'bogus')", [sid],
            )

    def test_budget_component_enum(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO budgets (sim_id, timestep, component, "
                "flux_in, flux_out) VALUES (?, 0, 'unknown', 0, 0)", [sid],
            )

    def test_bbox_order_enforced(self, mem_conn):
        sid = _sim_id()
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO simulations (sim_id, project, solver, "
                "bbox_xmin, bbox_xmax) VALUES (?, 'p', 'mf6', 10, 0)", [sid],
            )
