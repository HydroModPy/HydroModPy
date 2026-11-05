"""The index schema: its tables, its columns, its version stamp, and what it no longer holds."""

from __future__ import annotations

import duckdb
import pytest

from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.catalog.index_schema import (
    INDEX_SCHEMA_VERSION,
    create_index_schema,
    read_index_schema_version,
)
from hydromodpy.results.catalog.views import VIEW_NAMES
from tests._helpers.sealed_runs import make_project, seal_run

EXPECTED_TABLES = frozenset(
    {
        "index_meta",
        "solvers",
        "statuses",
        "flow_regimes",
        "mesh_topologies",
        "sites",
        "cases",
        "attempts",
        "simulations",
        "parameters",
        "metrics",
        "runs_environment",
        "provenance",
        "tracked_files",
        "geographic_features",
        "geographic_metadata",
        "tags",
        "sim_notes",
        "calibration_sessions",
        "calibration_session_cases",
        "calibration_phases",
        "calibration_iterations",
        "calibration_trial_cases",
    }
)

RETIRED_TABLES = frozenset(
    {
        "workflow_steps",
        "workflow_events",
        "audit_log",
        "export_log",
        "deletions",
        "purge_journal",
        "observations",
        "stations",
        "schema_migrations",
        "_schema_version",
    }
)

RETIRED_COLUMNS = frozenset(
    {"storage_basename", "study_area_name", "outlet_x", "outlet_y", "zarr_path", "trashed_at"}
    | {"nse_station", "nse_variable", "nse_window_start", "nse_window_end", "nse_n"}
    | {"objective_name", "objective_value", "objective_window_start", "objective_window_end"}
    | {"cost_name", "cost"}
)

SESSION_TABLE_COLUMNS = {
    "calibration_sessions": {
        "session_id",
        "rel_dir",
        "case_id",
        "project",
        "config_hash",
        "hydromodpy_version",
        "method",
        "sites",
        "bounds",
        "cost_name",
        "windows",
        "n_trials",
        "best_trial",
        "best_cost",
        "status",
        "started_at",
        "ended_at",
        "error_message",
        "root_search",
        "widths",
    },
    "calibration_session_cases": {
        "session_id",
        "case_id",
        "site",
        "config_hash",
        "best_sim_id",
        "best_rel_dir",
        "best_cost",
    },
    "calibration_phases": {
        "session_id",
        "phase_id",
        "name",
        "phase_index",
        "status",
        "frozen",
        "windows",
        "best_trial",
        "best_cost",
        "restarts",
    },
    "calibration_iterations": {
        "session_id",
        "trial",
        "phase",
        "restart",
        "params",
        "cost",
        "status",
        "started_at",
        "ended_at",
    },
    "calibration_trial_cases": {
        "session_id",
        "trial",
        "case_id",
        "cost",
        "status",
        "params_hash",
        "from_cache",
        "components",
        "sim_id",
        "rel_dir",
    },
    "metrics": {
        "sim_id",
        "station_id",
        "variable",
        "metric_name",
        "value",
        "window_name",
        "window_role",
        "window_start",
        "window_end",
        "n_samples",
        "n_clipped",
        "n_sim_nan",
        "metric_rule_version",
    },
}


@pytest.fixture
def connection():
    conn = duckdb.connect(":memory:")
    create_index_schema(conn, hydromodpy_version="2.0.0a5")
    try:
        yield conn
    finally:
        conn.close()


def _tables(conn) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
    ).fetchall()
    return {row[0] for row in rows}


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]
    ).fetchall()
    return {row[0] for row in rows}


def test_the_ddl_creates_every_table_and_none_of_the_retired_ones(connection):
    present = _tables(connection)
    assert EXPECTED_TABLES <= present
    assert not (RETIRED_TABLES & present)


def test_simulations_carries_the_site_case_attempt_label_and_rule_columns(connection):
    columns = _columns(connection, "simulations")
    assert {
        "site",
        "site_fingerprint",
        "recipe",
        "case_id",
        "rel_dir",
        "attempt",
        "attempt_id",
        "label",
        "label_date",
        "rule_version",
        "nse",
        "score_station",
        "score_variable",
        "score_window_start",
        "score_window_end",
        "n_samples",
        "metric_rule_version",
        "calibrated_by_session_id",
        "calibrated_by_window_start",
        "calibrated_by_window_end",
        "calibrated_by_metric",
        "calibrated_by_cost",
        "config_snapshot",
    } <= columns
    assert not (RETIRED_COLUMNS & columns)


@pytest.mark.parametrize("table", sorted(SESSION_TABLE_COLUMNS))
def test_the_session_and_metric_tables_hold_one_row_per_case_and_period(connection, table):
    assert _columns(connection, table) == SESSION_TABLE_COLUMNS[table]


def test_the_schema_version_is_stamped_and_read_back(connection):
    assert read_index_schema_version(connection) == INDEX_SCHEMA_VERSION == "10"


def test_a_file_without_the_stamp_has_no_version():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE simulations (sim_id VARCHAR)")
    assert read_index_schema_version(conn) is None
    conn.close()


def test_a_built_index_carries_the_views_and_the_parquet_views(tmp_path):
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    rebuild_index(root)

    with Catalog(root) as catalog:
        tables = set(catalog.tables())
        assert set(VIEW_NAMES) <= tables
        assert {"timeseries", "budgets", "mass_balance"} <= tables
        assert "cases" in tables
    stored = duckdb.connect(str(catalog_path_for(root)), read_only=True)
    try:
        views = {
            row[0]
            for row in stored.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_type = 'VIEW'"
            ).fetchall()
        }
    finally:
        stored.close()
    assert set(VIEW_NAMES) <= views
    assert "timeseries" not in views
