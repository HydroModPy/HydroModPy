"""Parquet tables of a run: the pyarrow schemas of the timeseries, metrics, budgets, mass balance and
provenance tables, the schema version stamped in each file, and the refusal of a file outside the
readable version window. Times are UTC.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.document_version import NEWER_REMEDY, OLDER_REMEDY
from hydromodpy.core.io.geoparquet import GEOPARQUET_SCHEMA_VERSION
from hydromodpy.results.catalog import parquet_views
from hydromodpy.results.catalog.constants import PARQUET_VIEW_NAMES
from hydromodpy.results.storage import run_store as run_store_module
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX
from hydromodpy.results.storage.parquet_io import read_kv_metadata
from hydromodpy.results.storage.parquet_schemas import (
    BUDGETS_SCHEMA,
    MASS_BALANCE_SCHEMA,
    METRICS_SCHEMA,
    PARQUET_SCHEMA_VERSION,
    PROVENANCE_SCHEMA,
    TIMESERIES_SCHEMA,
    VIEW_SCHEMAS,
    check_schema_version,
)
from tests._helpers.run_stores import open_run_store

VIEWS = ["timeseries", "budgets", "mass_balance", "metrics", "provenance"]


def head_series(n=5):
    index = pd.date_range("2020-01-01", periods=n)
    return pd.Series([float(i) for i in range(n)], index=index, name="head")


def store_with_head(project):
    store = open_run_store(project, "sim", create_zarr=False)
    store.write_timeseries(store.sim_id, "P01", "head", head_series(), unit="m")
    return store


def test_timeseries_schema():
    assert TIMESERIES_SCHEMA.names == [
        "sim_id",
        "station_id",
        "variable",
        "source",
        "component",
        "timestep",
        "time",
        "value",
        "unit",
    ]
    # A catchment series is at the station catchment: nothing here is null.
    for name in ("sim_id", "station_id", "variable", "source", "value"):
        assert TIMESERIES_SCHEMA.field(name).nullable is False


def test_metrics_schema():
    assert METRICS_SCHEMA.names == [
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
        "valid_from",
    ]
    assert METRICS_SCHEMA.field("value").nullable is True
    assert pa.types.is_date32(METRICS_SCHEMA.field("window_start").type)
    assert METRICS_SCHEMA.metadata[b"hmp.pk"] == b"sim_id,station_id,variable,metric,window_name"
    assert METRICS_SCHEMA.field("valid_from").nullable is False
    assert pa.types.is_timestamp(METRICS_SCHEMA.field("valid_from").type)
    assert METRICS_SCHEMA.field("valid_from").type.tz == "UTC"


def test_provenance_schema():
    for column in ("source_type", "source_ref", "payload_sha256"):
        assert column in PROVENANCE_SCHEMA.names
    assert PROVENANCE_SCHEMA.field("source_type").nullable is False


@pytest.mark.parametrize("schema", [BUDGETS_SCHEMA, MASS_BALANCE_SCHEMA])
def test_timestep_of_budget_tables(schema):
    assert "timestep" in schema.names
    assert pa.types.is_int64(schema.field("timestep").type)


@pytest.mark.parametrize("view", ["timeseries", "budgets", "mass_balance"])
def test_timestep_is_bigint(view):
    assert pa.types.is_int64(VIEW_SCHEMAS[view].field("timestep").type)


@pytest.mark.parametrize("view", VIEWS)
def test_every_view_has_a_schema(view):
    assert view in VIEW_SCHEMAS
    assert view in PARQUET_VIEW_NAMES


def test_schema_version_is_stored(tmp_path):
    with store_with_head(tmp_path) as store:
        target = store.tables_dir_for(store.sim_id) / f"timeseries{PARQUET_FILE_SUFFIX}"
    check_schema_version(pq.read_schema(target).metadata, document=target)
    assert read_kv_metadata(target)["hmp.schema_version"] == PARQUET_SCHEMA_VERSION


# A read and an append say the same thing about the same file.
STAMPS = [
    pytest.param(
        {b"hmp.schema_version": b"v9", b"hydromodpy_version": b"2.9.0"},
        "HydroModPy 2.9.0",
        id="newer, version named",
    ),
    pytest.param({b"hmp.schema_version": b"v9"}, NEWER_REMEDY, id="newer"),
    pytest.param({b"hmp.schema_version": b"v2"}, OLDER_REMEDY, id="older"),
    pytest.param({}, OLDER_REMEDY, id="no stamp"),
]


@pytest.mark.parametrize(("metadata", "said"), STAMPS)
def test_a_table_outside_the_window_is_refused(tmp_path, metadata, said):
    with store_with_head(tmp_path) as store:
        target = store.table_path_for(store.sim_id, "timeseries")
        pq.write_table(pq.read_table(target).replace_schema_metadata(metadata), target)
        doors = (
            lambda: store.read_table("timeseries"),
            lambda: store.write_timeseries(store.sim_id, "P02", "head", head_series()),
        )
        for door in doors:
            with pytest.raises(SchemaVersionMismatchError) as refused:
                door()
            assert said in str(refused.value)


def test_geoparquet_schema_version():
    # The OGC GeoParquet contract used by HMP v2 is 1.1.0.
    assert GEOPARQUET_SCHEMA_VERSION == "1.1.0"


def test_no_copy_to_parquet_in_results():
    # Parquet is written by pyarrow, never by a DuckDB COPY ... (FORMAT PARQUET).
    for module in (run_store_module, parquet_views):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert not re.search(r"COPY\s*\(.*?\)\s*TO\s*'.*?'\s*\(FORMAT PARQUET", source, re.DOTALL)
