"""The index schema: its tables, its columns read off the Parquet schemas, its version stamp."""

from __future__ import annotations

import duckdb
import pyarrow as pa
import pytest

from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.catalog.index_file import open_index
from hydromodpy.results.catalog.index_schema import (
    ARROW_TO_DUCKDB,
    INDEX_SCHEMA_VERSION,
    MIRRORED_TABLES,
    MirroredTable,
    arrow_type_key,
    create_index_schema,
    read_index_schema_version,
    table_ddl,
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
        "solution_key",
        "request_id",
    } <= columns
    assert not (RETIRED_COLUMNS & columns)


@pytest.mark.parametrize("table", sorted(SESSION_TABLE_COLUMNS))
def test_the_session_and_metric_tables_hold_one_row_per_case_and_period(connection, table):
    assert _columns(connection, table) == SESSION_TABLE_COLUMNS[table]


def test_the_schema_version_is_stamped_and_read_back(connection):
    assert read_index_schema_version(connection) == INDEX_SCHEMA_VERSION == "13"


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
    ("table", "arrow_field"),
    MIRRORED_CASES,
    ids=[f"{table.name}.{arrow_field.name}" for table, arrow_field in MIRRORED_CASES],
)
def test_each_parquet_column_is_in_its_table_with_its_type_and_nullity(
    connection, table, arrow_field
):
    columns = _described(connection, table.name)
    duckdb_type, nullable = columns[arrow_field.name]
    expected = table.types.get(arrow_field.name, ARROW_TO_DUCKDB[arrow_type_key(arrow_field.type)])
    assert DESCRIBED_AS.get(duckdb_type, duckdb_type) == expected.split()[0]
    assert nullable is (arrow_field.nullable and "PRIMARY KEY" not in expected)


@pytest.mark.parametrize("table", MIRRORED_TABLES, ids=lambda table: table.name)
def test_a_mirrored_table_holds_its_fields_codes_and_extras_and_nothing_else(connection, table):
    expected = {
        f"{field.name}_id" if field.name in table.coded else field.name
        for field in table.schema
        if field.name not in table.leave_out
    } | {name for name, _ in table.extra}
    assert set(_described(connection, table.name)) == expected


@pytest.mark.parametrize("table", MIRRORED_TABLES, ids=lambda table: table.name)
def test_the_columns_follow_the_order_of_the_schema(connection, table):
    expected = [
        f"{field.name}_id" if field.name in table.coded else field.name
        for field in table.schema
        if field.name not in table.leave_out
    ] + [name for name, _ in table.extra]
    assert list(_described(connection, table.name)) == expected


def test_every_arrow_type_of_a_mirrored_schema_is_mapped():
    used = {
        arrow_type_key(field.type)
        for table in MIRRORED_TABLES
        for field in table.schema
        if field.name not in table.types
        and field.name not in table.coded
        and field.name not in table.leave_out
    }
    assert used <= set(ARROW_TO_DUCKDB)


@pytest.mark.parametrize(
    ("arrow_type", "key"),
    [
        (pa.string(), "string"),
        (pa.float64(), "double"),
        (pa.float32(), "float"),
        (pa.int16(), "int16"),
        (pa.int32(), "int32"),
        (pa.int64(), "int64"),
        (pa.bool_(), "bool"),
        (pa.date32(), "date32[day]"),
        (pa.timestamp("ms", tz="UTC"), "timestamp[*, tz=UTC]"),
        (pa.timestamp("us", tz="UTC"), "timestamp[*, tz=UTC]"),
    ],
)
def test_an_arrow_type_has_its_key(arrow_type, key):
    assert arrow_type_key(arrow_type) == key
    assert key in ARROW_TO_DUCKDB


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


def test_the_metric_column_carries_the_parquet_name(connection):
    columns = _described(connection, "metrics")
    assert "metric" in columns
    assert "metric_name" not in columns
    assert "valid_from" not in columns


def test_cases_carries_the_size_of_the_directory(connection):
    assert _described(connection, "cases")["bytes"] == ("BIGINT", False)


def test_provenance_source_type_is_required_as_in_its_parquet(connection):
    assert _described(connection, "provenance")["source_type"] == ("VARCHAR", False)
