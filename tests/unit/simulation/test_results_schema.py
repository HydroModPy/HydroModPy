"""Tests for simulation/results/schema.py — DuckDB table creation."""

from __future__ import annotations

import duckdb
import pytest

from hydromodpy.results.schema import (
    PROJECT_GEOGRAPHIC_TABLE_NAMES,
    PROJECT_TABLE_NAMES,
    create_project_tables,
    create_registry_table,
)


@pytest.fixture
def mem_conn():
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


class TestProjectTables:
    def test_creates_all_tables(self, mem_conn):
        create_project_tables(mem_conn)
        tables = {
            r[0]
            for r in mem_conn.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        for name in PROJECT_TABLE_NAMES:
            assert name in tables, f"missing table {name}"

    def test_idempotent(self, mem_conn):
        create_project_tables(mem_conn)
        create_project_tables(mem_conn)
        count = mem_conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables"
        ).fetchone()[0]
        # +1 for the _schema_version metadata table
        assert count == len(PROJECT_TABLE_NAMES) + len(PROJECT_GEOGRAPHIC_TABLE_NAMES) + 1

    def test_simulations_columns(self, mem_conn):
        create_project_tables(mem_conn)
        cols = {
            r[0]
            for r in mem_conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'simulations'"
            ).fetchall()
        }
        expected = {
            "sim_id", "name", "created_at", "config_toml", "solver",
            "n_cells", "n_layers", "n_timesteps", "cell_types", "bbox",
            "zarr_group", "status", "duration_s", "tags",
        }
        assert expected <= cols


class TestRegistryTable:
    def test_creates_table(self, mem_conn):
        create_registry_table(mem_conn)
        tables = {
            r[0]
            for r in mem_conn.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        assert "simulation_registry" in tables

    def test_idempotent(self, mem_conn):
        create_registry_table(mem_conn)
        create_registry_table(mem_conn)

    def test_indexes_created(self, mem_conn):
        create_registry_table(mem_conn)
        indexes = {
            r[0]
            for r in mem_conn.execute(
                "SELECT index_name FROM duckdb_indexes()"
            ).fetchall()
        }
        for ix in (
            "ix_registry_project",
            "ix_registry_solver",
            "ix_registry_status",
            "ix_registry_created",
        ):
            assert ix in indexes, f"missing index {ix}"

    def test_registry_columns(self, mem_conn):
        create_registry_table(mem_conn)
        cols = {
            r[0]
            for r in mem_conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'simulation_registry'"
            ).fetchall()
        }
        expected = {
            "sim_id", "project", "project_path", "solver", "status",
            "best_nse", "best_kge", "config_hash", "forcing_sources",
        }
        assert expected <= cols
