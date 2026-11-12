"""The index schema: its version stamp, its views, and the tables copied from Parquet schemas.

A column of a mirrored table takes its DuckDB type from the Arrow type of the
Parquet schema. A coded field points to its dimension table by an id.
"""

from __future__ import annotations

import duckdb
import pyarrow as pa
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.index_file import open_index
from hydromodpy.results.catalog.index_schema import (
    MirroredTable,
    read_index_schema_version,
    table_ddl,
)
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.catalog.views import VIEW_NAMES
from tests._helpers.sealed_runs import make_project, seal_run


def test_a_file_without_the_stamp_has_no_version():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE simulations (sim_id VARCHAR)")
    assert read_index_schema_version(conn) is None
    conn.close()


def test_views_of_a_built_index(tmp_path):
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


def test_a_coded_field_joins_its_dimension_table():
    table = MirroredTable(
        name="probe",
        schema=pa.schema([pa.field("solver", pa.string(), nullable=False)]),
        coded={"solver": "solvers"},
    )
    assert "solver_id SMALLINT NOT NULL REFERENCES solvers(id)" in table_ddl(table)


ARROW_TYPES = [
    pytest.param(pa.large_string(), id="large_string"),
    pytest.param(pa.timestamp("ms"), id="naive-timestamp"),
    pytest.param(pa.list_(pa.int32()), id="list"),
]


@pytest.mark.parametrize("arrow_type", ARROW_TYPES)
def test_unknown_arrow_type_is_refused(arrow_type):
    table = MirroredTable(name="probe", schema=pa.schema([pa.field("odd", arrow_type)]))
    with pytest.raises(KeyError, match=r"probe\.odd has Arrow type"):
        table_ddl(table)
