"""The index schema: its tables, its columns read off the Parquet schemas, its version stamp."""

from __future__ import annotations

import duckdb
import pyarrow as pa
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.index_file import open_index
from hydromodpy.results.catalog.index_schema import (
    MIRRORED_TABLES,
    MirroredTable,
    read_index_schema_version,
    table_ddl,
)
from hydromodpy.results.catalog.indexer import rebuild_index
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
    | {"config_hash"}
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
        "metric",
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
    stored = open_index(root)
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


# -- the tables copied from a Parquet schema ---------------------------------


def _described(conn, table: str) -> dict[str, tuple[str, bool]]:
    """Return ``{column: (DuckDB type, nullable)}``."""
    rows = conn.execute(f"DESCRIBE {table}").fetchall()
    return {str(row[0]): (str(row[1]), row[2] == "YES") for row in rows}


DESCRIBED_AS = {"TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ"}
"""The name ``DESCRIBE`` gives a type, when it is not the name the DDL writes."""

MIRRORED_CASES = [
    (table, arrow_field)
    for table in MIRRORED_TABLES
    for arrow_field in table.schema
    if arrow_field.name not in table.coded and arrow_field.name not in table.leave_out
]


@pytest.mark.parametrize(
    "arrow_type",
    [pa.large_string(), pa.timestamp("ms"), pa.list_(pa.int32())],
    ids=["large_string", "naive-timestamp", "list"],
)
def test_an_unknown_arrow_type_is_refused_with_its_field(arrow_type):
    table = MirroredTable(name="probe", schema=pa.schema([pa.field("odd", arrow_type)]))
    with pytest.raises(KeyError, match=r"probe\.odd has Arrow type"):
        table_ddl(table)


def test_a_coded_field_joins_its_dimension_table():
    table = MirroredTable(
        name="probe",
        schema=pa.schema([pa.field("solver", pa.string(), nullable=False)]),
        coded={"solver": "solvers"},
    )
    assert "solver_id SMALLINT NOT NULL REFERENCES solvers(id)" in table_ddl(table)
