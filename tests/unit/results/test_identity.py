"""Each applicator poses the identity block in its format, and the same module reads it back."""

from __future__ import annotations

import sqlite3

import geopandas as gpd
import matplotlib
import pyarrow as pa
import pyarrow.parquet as pq
import zarr
from shapely.geometry import Point

from hydromodpy.results.identity import GPKG_METADATA_URI, meta_sidecar_path, read_identity_from
from tests._helpers.run_records import make_identity

matplotlib.use("Agg")


def test_gpkg_block_written_once(tmp_path):
    identity = make_identity()
    path = tmp_path / "watershed.gpkg"
    gpd.GeoDataFrame({"id": [1]}, geometry=[Point(0, 0)], crs="EPSG:2154").to_file(
        path, driver="GPKG"
    )

    identity.write_gpkg_metadata(path)
    identity.write_gpkg_metadata(path)

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT md_scope, mime_type FROM gpkg_metadata WHERE md_standard_uri = ?",
            (GPKG_METADATA_URI,),
        ).fetchall()
        references = connection.execute(
            "SELECT reference_scope FROM gpkg_metadata_reference"
        ).fetchall()
        extensions = connection.execute(
            "SELECT table_name FROM gpkg_extensions WHERE extension_name = 'gpkg_metadata'"
        ).fetchall()
    assert rows == [("dataset", "application/json")]
    assert references == [("geopackage",)]
    assert sorted(extensions) == [("gpkg_metadata",), ("gpkg_metadata_reference",)]
    assert read_identity_from(path) == identity
    assert len(gpd.read_file(path)) == 1


def test_block_without_label():
    steady = make_identity(period=None)
    assert "steady state, no period" in steady.footer_text()
    assert steady.footer_text().endswith("unlabelled")
    assert "rule" not in steady.footer_text()


def test_csv_meta_sidecar(tmp_path):
    identity = make_identity()
    csv = tmp_path / "discharge.csv"
    csv.write_text("datetime,value\n2016-01-01,1.0\n", encoding="utf-8")

    sidecar = identity.write_meta_json(csv)

    assert sidecar == tmp_path / "discharge.csv.meta.json" == meta_sidecar_path(csv)
    assert read_identity_from(csv) == identity
    assert read_identity_from(sidecar) == identity


def test_file_without_block(tmp_path):
    pq.write_table(pa.table({"value": [1.0]}), tmp_path / "bare.parquet")
    (tmp_path / "bare.csv").write_text("a\n", encoding="utf-8")
    zarr.open_group(str(tmp_path / "bare.zarr"), mode="w")
    gpd.GeoDataFrame({"id": [1]}, geometry=[Point(0, 0)], crs="EPSG:2154").to_file(
        tmp_path / "bare.gpkg", driver="GPKG"
    )

    for name in ("bare.parquet", "bare.csv", "bare.zarr", "bare.gpkg"):
        assert read_identity_from(tmp_path / name) is None
