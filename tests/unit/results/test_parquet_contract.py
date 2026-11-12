"""Parquet table contract tests.

Cover the pyarrow schemas declared in
:mod:`hydromodpy.results.storage.parquet_schemas`, the atomic writer in
:mod:`hydromodpy.results.storage.parquet_io`, the OGC GeoParquet 1.1 round-trip via
:mod:`hydromodpy.core.io.geoparquet`, the batched timeseries writer, the
lazy loaders, the enriched KV metadata, and the schema-version enforcement.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.document_version import NEWER_REMEDY, OLDER_REMEDY
from hydromodpy.core.io.geoparquet import GEOPARQUET_SCHEMA_VERSION
from hydromodpy.results.catalog.constants import PARQUET_VIEW_NAMES
from hydromodpy.results.catalog.indexer import rebuild_index
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
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


def _store(project: Path, name: str = "sim") -> RunStore:
    """Claim ``runs/<name>`` and open its store, without a field store."""
    return open_run_store(project, name, create_zarr=False)


def _seal_and_index(project: Path, *stores: RunStore) -> None:
    for store in stores:
        seal_completed(store)
    rebuild_index(project)


def _make_series(n: int = 5, start: str = "2020-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=n)
    return pd.Series([float(i) for i in range(n)], index=idx, name="head")


class TestSchemasStrict:
    def test_schema_strict_for_timeseries(self):
        names = TIMESERIES_SCHEMA.names
        assert names == [
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

    def test_schema_strict_for_metrics(self):
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
        assert (
            METRICS_SCHEMA.metadata[b"hmp.pk"] == b"sim_id,station_id,variable,metric,window_name"
        )
        assert METRICS_SCHEMA.field("valid_from").nullable is False
        assert pa.types.is_timestamp(METRICS_SCHEMA.field("valid_from").type)
        assert METRICS_SCHEMA.field("valid_from").type.tz == "UTC"

    def test_schema_strict_for_budgets_and_mass_balance(self):
        assert "timestep" in BUDGETS_SCHEMA.names
        assert "timestep" in MASS_BALANCE_SCHEMA.names
        for s in (BUDGETS_SCHEMA, MASS_BALANCE_SCHEMA):
            assert pa.types.is_int64(s.field("timestep").type)

    def test_schema_strict_for_provenance(self):
        names = PROVENANCE_SCHEMA.names
        for col in ("source_type", "source_ref", "payload_sha256"):
            assert col in names
        assert PROVENANCE_SCHEMA.field("source_type").nullable is False

    def test_view_schemas_cover_view_names(self):
        # Every PARQUET_VIEW_NAME maps to a schema.
        for view in ("timeseries", "budgets", "mass_balance", "metrics", "provenance"):
            assert view in VIEW_SCHEMAS
            assert view in PARQUET_VIEW_NAMES


class TestTimestepBigint:
    def test_timestep_is_bigint(self):
        for view in ("timeseries", "budgets", "mass_balance"):
            field = VIEW_SCHEMAS[view].field("timestep")
            assert pa.types.is_int64(field.type)


class TestMetricsProvenanceInViewNames:
    @pytest.mark.parametrize("view", ["metrics", "provenance"])
    def test_the_parquet_table_is_a_view_name(self, view):
        assert view in PARQUET_VIEW_NAMES


class TestSchemaVersion:
    def test_parquet_schema_version_stored(self, tmp_path: Path):
        with _store(tmp_path) as store:
            sid = store.sim_id
            store.write_timeseries(sid, "P01", "head", _make_series(), unit="m")
            target = store.tables_dir_for(sid) / f"timeseries{PARQUET_FILE_SUFFIX}"
        check_schema_version(pq.read_schema(target).metadata, document=target)
        assert read_kv_metadata(target)["hmp.schema_version"] == PARQUET_SCHEMA_VERSION

    @pytest.mark.parametrize(
        ("metadata", "said"),
        [
            ({b"hmp.schema_version": b"v9", b"hydromodpy_version": b"2.9.0"}, "HydroModPy 2.9.0"),
            ({b"hmp.schema_version": b"v9"}, NEWER_REMEDY),
            ({b"hmp.schema_version": b"v2"}, OLDER_REMEDY),
            ({}, OLDER_REMEDY),
        ],
    )
    def test_a_table_outside_the_window_is_refused_by_every_door(
        self, tmp_path: Path, metadata: dict[bytes, bytes], said: str
    ):
        """A read and an append say the same thing about the same file."""
        with _store(tmp_path) as store:
            store.write_timeseries(store.sim_id, "P01", "head", _make_series(), unit="m")
            target = store.table_path_for(store.sim_id, "timeseries")
            table = pq.read_table(target).replace_schema_metadata(metadata)
            pq.write_table(table, target)
            for door in (
                lambda: store.read_table("timeseries"),
                lambda: store.write_timeseries(store.sim_id, "P02", "head", _make_series()),
            ):
                with pytest.raises(SchemaVersionMismatchError) as refused:
                    door()
                assert said in str(refused.value)


class TestGeoParquetOgc:
    def test_geoparquet_schema_version(self):
        # The OGC GeoParquet contract used by HMP v2 is 1.1.0.
        assert GEOPARQUET_SCHEMA_VERSION == "1.1.0"


class TestCopyToParquetGone:
    def test_no_copy_to_parquet_in_results(self):
        """Ensure no DuckDB COPY ... (FORMAT PARQUET) in the results layer."""
        import re

        from hydromodpy.results.catalog import parquet_views as views_mod
        from hydromodpy.results.storage import run_store as run_store_mod

        for mod in (run_store_mod, views_mod):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            assert not re.search(r"COPY\s*\(.*?\)\s*TO\s*'.*?'\s*\(FORMAT PARQUET", src, re.DOTALL)
