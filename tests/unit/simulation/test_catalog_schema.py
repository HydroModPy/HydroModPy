from __future__ import annotations

import duckdb
import pytest

from hydromodpy.results.catalog_schema import (
    LATEST_VERSION,
    TABLE_NAMES,
    ensure_schema,
)


@pytest.fixture
def mem_conn():
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


def _table_names(conn: duckdb.DuckDBPyConnection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }


def _column_names(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?",
            [table],
        ).fetchall()
    }


class TestSchemaCreation:
    def test_creates_all_tables(self, mem_conn):
        ensure_schema(mem_conn)
        tables = _table_names(mem_conn)
        for name in TABLE_NAMES:
            assert name in tables, f"Missing table: {name}"
        assert "_schema_version" in tables

    def test_version_stamped(self, mem_conn):
        ensure_schema(mem_conn)
        row = mem_conn.execute(
            "SELECT MAX(version) FROM _schema_version"
        ).fetchone()
        assert row[0] == LATEST_VERSION

    def test_simulations_columns(self, mem_conn):
        ensure_schema(mem_conn)
        cols = _column_names(mem_conn, "simulations")
        expected = {
            "sim_id", "name", "project", "solver", "solver_category",
            "flow_regime", "n_cells", "n_layers", "n_timesteps",
            "cell_types", "bbox", "crs", "period_start", "period_end",
            "time_unit", "config_toml", "config_hash", "zarr_path",
            "parent_sim_id", "mesh_hash", "mesh_type", "status",
            "duration_s", "created_at", "tags", "notes",
        }
        for col in expected:
            assert col in cols, f"Missing column: {col}"

    def test_parameters_has_zone_id(self, mem_conn):
        ensure_schema(mem_conn)
        cols = _column_names(mem_conn, "parameters")
        assert "zone_id" in cols
        assert "parameterization" in cols

    def test_mass_balance_name(self, mem_conn):
        ensure_schema(mem_conn)
        tables = _table_names(mem_conn)
        assert "mass_balance" in tables
        assert "mass_balance_summary" not in tables

    def test_provenance_name(self, mem_conn):
        ensure_schema(mem_conn)
        tables = _table_names(mem_conn)
        assert "provenance" in tables
        assert "input_provenance" not in tables

    def test_calibration_tables(self, mem_conn):
        ensure_schema(mem_conn)
        tables = _table_names(mem_conn)
        assert "calibration_sessions" in tables
        assert "calibration_iterations" in tables

    def test_geographic_tables_have_sim_id(self, mem_conn):
        ensure_schema(mem_conn)
        for tbl in ("geographic_features", "geographic_metadata"):
            cols = _column_names(mem_conn, tbl)
            assert "sim_id" in cols, f"Missing 'sim_id' in {tbl}"

    def test_budgets_zone_id_varchar(self, mem_conn):
        ensure_schema(mem_conn)
        row = mem_conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'budgets' AND column_name = 'zone_id'"
        ).fetchone()
        assert row is not None
        assert "VARCHAR" in row[0].upper()


class TestIdempotent:
    def test_double_call(self, mem_conn):
        ensure_schema(mem_conn)
        ensure_schema(mem_conn)
        tables = _table_names(mem_conn)
        for name in TABLE_NAMES:
            assert name in tables


class TestPrimaryKeys:
    def test_parameters_pk_rejects_duplicate(self, mem_conn):
        ensure_schema(mem_conn)
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'test', 'mf6')"
        )
        mem_conn.execute(
            "INSERT INTO parameters (sim_id, param_name, zone_id, value) "
            "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'K', '_homogeneous', 1.0)"
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO parameters (sim_id, param_name, zone_id, value) "
                "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'K', '_homogeneous', 2.0)"
            )

    def test_metrics_pk_rejects_duplicate(self, mem_conn):
        ensure_schema(mem_conn)
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'test', 'mf6')"
        )
        mem_conn.execute(
            "INSERT INTO metrics (sim_id, station_id, metric_name, value) "
            "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'P01', 'nse', 0.8)"
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO metrics (sim_id, station_id, metric_name, value) "
                "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'P01', 'nse', 0.9)"
            )

    def test_geographic_features_pk(self, mem_conn):
        ensure_schema(mem_conn)
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'test', 'mf6')"
        )
        mem_conn.execute(
            "INSERT INTO geographic_features (sim_id, feature_name, geojson) "
            "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'watershed', '{}')"
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO geographic_features (sim_id, feature_name, geojson) "
                "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'watershed', '{}')"
            )
