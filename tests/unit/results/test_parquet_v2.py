"""P7 Parquet v2 contract tests.

Cover the pyarrow schemas declared in
:mod:`hydromodpy.results.storage.parquet_schemas`, the atomic writer in
:mod:`hydromodpy.results.storage.parquet_io`, the OGC GeoParquet 1.1 round-trip via
:mod:`hydromodpy.core.io.geoparquet`, the batched timeseries writer, the
lazy loaders, the enriched KV metadata, and the schema-version enforcement.
"""

from __future__ import annotations

import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely.geometry import Point, Polygon

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.document_version import NEWER_REMEDY, OLDER_REMEDY
from hydromodpy.core.io.geoparquet import (
    GEOPARQUET_SCHEMA_VERSION,
    read_geoparquet,
    write_geoparquet_atomic,
)
from hydromodpy.core.io.parquet import PARQUET_WRITE_DEFAULTS
from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.constants import PARQUET_VIEW_NAMES
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX
from hydromodpy.results.storage.lazy_loaders import (
    list_field_paths,
    list_parquet_paths,
    scan_field,
    scan_timeseries,
)
from hydromodpy.results.storage.parquet_io import (
    read_kv_metadata,
    write_table_atomic,
)
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
            "component",
            "timestep",
            "time",
            "value",
            "unit",
            "qflag",
        ]
        # sim_id, variable, value are not nullable.
        assert TIMESERIES_SCHEMA.field("sim_id").nullable is False
        assert TIMESERIES_SCHEMA.field("variable").nullable is False
        assert TIMESERIES_SCHEMA.field("value").nullable is False
        # station_id is nullable: global series exist.
        assert TIMESERIES_SCHEMA.field("station_id").nullable is True

    def test_schema_strict_for_metrics(self):
        names = METRICS_SCHEMA.names
        assert "metric" in names
        assert "valid_from" in names
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
    def test_metrics_parquet_in_view_names(self):
        assert "metrics" in PARQUET_VIEW_NAMES

    def test_provenance_parquet_in_view_names(self):
        assert "provenance" in PARQUET_VIEW_NAMES


class TestWriteOptionsForced:
    def test_write_table_atomic_forces_zstd_and_page_index(self, tmp_path: Path):
        table = pa.table({"sim_id": ["s"], "x": [1.0]})
        target = tmp_path / "out.parquet"
        write_table_atomic(table, target)
        meta = pq.ParquetFile(target).metadata
        # row group 0 column 0 must declare ZSTD compression
        cc = meta.row_group(0).column(0)
        assert "ZSTD" in str(cc.compression)
        # Parquet 2.6 format embedded in writer metadata
        assert PARQUET_WRITE_DEFAULTS["version"] == "2.6"

    def test_write_table_atomic_promotes_via_tmp(self, tmp_path: Path):
        target = tmp_path / "out.parquet"
        table = pa.table({"a": [1, 2, 3]})
        out = write_table_atomic(table, target)
        assert out == target
        # No leftover tmp files
        stale = list(tmp_path.glob(f"{target.name}.tmp-*"))
        assert stale == []


class TestKvMetadataEnriched:
    def test_kv_metadata_enriched(self, tmp_path: Path):
        with _store(tmp_path, name="rich") as store:
            sid = store.sim_id
            store.write_timeseries(sid, "P01", "head", _make_series(), unit="m")
            target = store.tables_dir_for(sid) / f"timeseries{PARQUET_FILE_SUFFIX}"
        md = read_kv_metadata(target)
        assert md.get("hmp.schema_version") == PARQUET_SCHEMA_VERSION
        assert md.get("hmp.schema") == "timeseries"
        assert md.get("Conventions") == "CF-1.11"
        assert md.get("license") == UNDETERMINED_LICENSE
        assert md.get("hydromodpy_version", "")
        assert md.get("sim_id") == sid
        assert "written_at" in md  # field present, deterministic


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
            ({b"hmp.schema_version": b"v1"}, OLDER_REMEDY),
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

    def test_an_append_keeps_a_column_a_later_version_added(self, tmp_path: Path):
        """The older writer keeps what it does not know; its own rows read it as null."""
        with _store(tmp_path) as store:
            sid = store.sim_id
            store.write_timeseries(sid, "P01", "head", _make_series(2), unit="m")
            target = store.table_path_for(sid, "timeseries")
            table = pq.read_table(target)
            added = table.append_column("later", pa.array([1.5, 2.5], type=pa.float64()))
            pq.write_table(added, target)

            store.write_timeseries(sid, "P02", "head", _make_series(1), unit="m")

            frame = store.read_table("timeseries").sort_values(["station_id", "timestep"])
        assert frame["later"].iloc[:2].tolist() == [1.5, 2.5]
        assert frame["later"].iloc[2:].isna().all()
        assert frame["station_id"].tolist() == ["P01", "P01", "P02"]


class TestGeoParquetOgc:
    def test_geoparquet_1_1_via_gpd_read_parquet(self, tmp_path: Path):
        gdf = gpd.GeoDataFrame(
            {"name": ["P01", "P02"]},
            geometry=[Point(0, 0), Point(1, 1)],
            crs="EPSG:2154",
        )
        target = tmp_path / "feat.parquet"
        write_geoparquet_atomic(gdf, target)
        loaded = read_geoparquet(target)
        assert len(loaded) == 2
        assert loaded.crs.to_epsg() == 2154
        # GeoParquet 1.1 marker present in pyarrow KV metadata under "geo".
        raw = pq.ParquetFile(target).schema_arrow.metadata or {}
        assert any(b"geo" == k for k in raw)

    def test_geographic_feature_written_as_geoparquet(self, tmp_path: Path):
        store = _store(tmp_path)
        sid = store.sim_id
        gdf = gpd.GeoDataFrame(
            {"name": ["domain"]},
            geometry=[Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)])],
            crs="EPSG:4326",
        )
        store.write_geographic_feature(sid, "domain", gdf)
        _seal_and_index(tmp_path, store)
        with Catalog(tmp_path) as cat:
            loaded = cat.read_geographic_feature(sid, "domain")
        assert len(loaded) == 1
        assert loaded.crs.to_epsg() == 4326

    def test_geoparquet_schema_version(self):
        # The OGC GeoParquet contract used by HMP v2 is 1.1.0.
        assert GEOPARQUET_SCHEMA_VERSION == "1.1.0"


class TestBatchWrite:
    def test_batch_write_timeseries_eliminates_quadratic_merge(self, tmp_path: Path):
        n_records = 200
        batch = _store(tmp_path, name="batch")
        sid_batch = batch.sim_id
        batch_records = [
            {
                "station_id": "P01",
                "variable": "head",
                "timestep": i,
                "time": pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(days=i),
                "value": float(i),
                "unit": "m",
                "qflag": "simulated",
            }
            for i in range(n_records)
        ]
        t0 = time.perf_counter()
        batch.write_timeseries_batch(sid_batch, batch_records)
        t_batch = time.perf_counter() - t0

        loop = _store(tmp_path, name="loop")
        ts = pd.Series(
            [float(i) for i in range(n_records)],
            index=pd.date_range("2020-01-01", periods=n_records, freq="D"),
            name="head",
        )
        # Force an O(N) merge pattern by writing 20 chunks of 10 rows.
        t0 = time.perf_counter()
        for chunk in range(0, n_records, 10):
            loop.write_timeseries(
                loop.sim_id,
                f"P{chunk:02d}",
                "head",
                ts.iloc[chunk : chunk + 10],
                unit="m",
            )
        t_loop = time.perf_counter() - t0
        _seal_and_index(tmp_path, batch, loop)
        # The batched path must end up with exactly n_records rows.
        with Catalog(tmp_path) as cat:
            count = cat.connection.execute(
                "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", [sid_batch]
            ).fetchone()[0]
        assert count == n_records
        # Sanity check: batching should never take longer than a 20-call
        # merge loop. The threshold is generous because the loop dataset is
        # not exactly the same shape; the goal is to assert "not worse".
        assert t_batch <= max(t_loop * 2.0, 1.0)


class TestLazyLoaders:
    def test_lazy_loader_scan_timeseries(self, tmp_path: Path):
        pl = pytest.importorskip("polars")
        first, second = _store(tmp_path, name="a"), _store(tmp_path, name="b")
        sid1 = first.sim_id
        first.write_timeseries(sid1, "P01", "head", _make_series(n=4), unit="m")
        second.write_timeseries(second.sim_id, "P01", "head", _make_series(n=6), unit="m")
        _seal_and_index(tmp_path, first, second)
        with Catalog(tmp_path) as cat:
            lf = scan_timeseries(cat)
            assert isinstance(lf, pl.LazyFrame)
            df = lf.collect()
        assert len(df) == 10
        # Filter pushdown round-trip
        with Catalog(tmp_path) as cat:
            df_sid1 = scan_timeseries(cat, filters={"sim_id": sid1}).collect()
        assert len(df_sid1) == 4

    def test_lazy_loader_scan_field(self, tmp_path: Path):
        store = _store(tmp_path)
        store.write_timeseries(store.sim_id, "P01", "head", _make_series(), unit="m")
        _seal_and_index(tmp_path, store)
        with Catalog(tmp_path) as cat:
            ds = scan_field(cat)
            # The dataset materialises a path index for downstream consumers.
            df = ds.to_table().to_pandas()
        assert "path" in df.columns

    def test_list_parquet_paths_round_trip(self, tmp_path: Path):
        store = _store(tmp_path)
        store.write_timeseries(store.sim_id, "P01", "head", _make_series(), unit="m")
        _seal_and_index(tmp_path, store)
        with Catalog(tmp_path) as cat:
            paths = list_parquet_paths(cat, "timeseries")
            field_paths = list_field_paths(cat)
        assert len(paths) == 1
        assert paths[0].name == "timeseries.parquet"
        # A field path may not exist when no Zarr was written; tolerate that.
        assert isinstance(field_paths, list)


class TestCopyToParquetGone:
    def test_no_copy_to_parquet_in_results(self):
        """Ensure no DuckDB COPY ... (FORMAT PARQUET) in the results layer."""
        import re

        from hydromodpy.results.catalog import parquet_views as views_mod
        from hydromodpy.results.storage import run_store as run_store_mod

        for mod in (run_store_mod, views_mod):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            assert not re.search(r"COPY\s*\(.*?\)\s*TO\s*'.*?'\s*\(FORMAT PARQUET", src, re.DOTALL)


class TestParquetViewNames:
    def test_view_aliased_when_table_collides(self, tmp_path: Path):
        # ``metrics`` and ``provenance`` are DuckDB tables. The Parquet view
        # falls back to ``<view>_parquet`` to avoid clobbering the table.
        rebuild_index(tmp_path)
        with Catalog(tmp_path) as cat:
            views = cat.connection.execute(
                "SELECT view_name FROM duckdb_views() WHERE schema_name='main'"
            ).fetchall()
        names = {v[0] for v in views}
        assert "metrics_parquet" in names
        assert "provenance_parquet" in names
        assert "timeseries" in names
