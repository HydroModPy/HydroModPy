"""Each applicator poses the identity block in its format, and the same module reads it back."""

from __future__ import annotations

import sqlite3
from datetime import date

import geopandas as gpd
import matplotlib
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import zarr
from PIL import Image
from pydantic import ValidationError
from shapely.geometry import Point

from hydromodpy.results.identity import (
    GPKG_METADATA_URI,
    PNG_IDENTITY_KEY,
    ZARR_IDENTITY_ATTR,
    Identity,
    meta_sidecar_path,
    read_identity_from,
)
from tests._helpers.run_records import make_identity

matplotlib.use("Agg")


def test_zarr_root_attributes_carry_the_block_and_the_acdd_words(tmp_path):
    identity = make_identity()
    store = tmp_path / "fields.zarr"
    group = zarr.open_group(str(store), mode="w")
    identity.apply_to_zarr(group)

    attrs = dict(zarr.open_group(str(store), mode="r").attrs)
    assert attrs["hydromodpy_site"] == "J0014010"
    assert attrs["project"] == "J0014010"
    assert attrs["processing_level"] == "Modeled L2"
    assert attrs[ZARR_IDENTITY_ATTR]["sim_id"] == identity.sim_id
    assert read_identity_from(store) == identity


def test_a_labelled_block_derives_the_processing_level(tmp_path):
    labelled = make_identity().labelled(
        "calibrated", label_date=date(2026, 10, 15), rule_version="1"
    )
    attrs = labelled.as_zarr_attrs()
    assert attrs["processing_level"] == "Modeled L3 (calibrated)"
    assert attrs["hydromodpy_label"] == "calibrated"


def test_parquet_schema_metadata_carries_the_block(tmp_path):
    identity = make_identity()
    table = pa.table({"value": [1.0]}).replace_schema_metadata(identity.as_parquet_metadata())
    pq.write_table(table, tmp_path / "discharge.parquet")

    assert read_identity_from(tmp_path / "discharge.parquet") == identity


def test_gpkg_metadata_table_carries_the_block_once_even_when_written_twice(tmp_path):
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


def test_png_text_chunk_carries_the_block_and_the_footer_is_drawn(tmp_path):
    import matplotlib.pyplot as plt

    identity = make_identity().labelled(
        "evaluated", label_date=date(2026, 10, 15), rule_version="1"
    )
    path = tmp_path / "heads.png"
    figure, axis = plt.subplots()
    axis.plot([0, 1], [0, 1])
    figure.text(0.5, 0.01, identity.footer_text(), ha="center")
    figure.savefig(path, metadata=identity.as_png_metadata())
    plt.close(figure)

    with Image.open(path) as image:
        assert PNG_IDENTITY_KEY in image.text
        assert image.text["Software"].startswith("HydroModPy ")
    assert read_identity_from(path) == identity


@pytest.mark.parametrize(
    ("label", "rule", "day", "tail"),
    [
        ("calibrated", "1", date(2026, 10, 15), "calibrated, rule 1, 2026-10-15"),
        ("evaluated", "2", date(2026, 11, 11), "evaluated, rule 2, 2026-11-11"),
        ("exploratory", "1", date(2027, 1, 2), "exploratory, rule 1, 2027-01-02"),
    ],
)
def test_the_footer_names_site_period_version_label_rule_and_date(label, rule, day, tail):
    labelled = make_identity().labelled(label, label_date=day, rule_version=rule)
    assert labelled.footer_text() == (
        f"J0014010 · 2016-01-01 to 2020-12-31 · HydroModPy 2.0.0a5 · {tail}"
    )


def test_a_block_without_a_label_reads_unlabelled():
    steady = make_identity(period=None)
    assert "steady state, no period" in steady.footer_text()
    assert steady.footer_text().endswith("unlabelled")
    assert "rule" not in steady.footer_text()


def test_a_csv_gets_a_meta_json_sidecar_next_to_it(tmp_path):
    identity = make_identity()
    csv = tmp_path / "discharge.csv"
    csv.write_text("datetime,value\n2016-01-01,1.0\n", encoding="utf-8")

    sidecar = identity.write_meta_json(csv)

    assert sidecar == tmp_path / "discharge.csv.meta.json" == meta_sidecar_path(csv)
    assert read_identity_from(csv) == identity
    assert read_identity_from(sidecar) == identity


def test_two_files_of_one_stem_never_share_a_sidecar(tmp_path):
    assert meta_sidecar_path(tmp_path / "discharge.csv") != meta_sidecar_path(
        tmp_path / "discharge.parquet"
    )


def test_a_file_without_the_block_reads_as_none(tmp_path):
    pq.write_table(pa.table({"value": [1.0]}), tmp_path / "bare.parquet")
    (tmp_path / "bare.csv").write_text("a\n", encoding="utf-8")
    zarr.open_group(str(tmp_path / "bare.zarr"), mode="w")
    gpd.GeoDataFrame({"id": [1]}, geometry=[Point(0, 0)], crs="EPSG:2154").to_file(
        tmp_path / "bare.gpkg", driver="GPKG"
    )

    for name in ("bare.parquet", "bare.csv", "bare.zarr", "bare.gpkg"):
        assert read_identity_from(tmp_path / name) is None


def test_the_seal_block_is_label_free_until_labelled():
    identity = make_identity()
    assert identity.label is None and identity.label_date is None
    labelled = identity.labelled("exploratory", label_date=date(2026, 10, 15), rule_version="1")
    assert labelled.label == "exploratory" and identity.label is None


def test_an_unknown_label_or_key_is_refused_by_name():
    with pytest.raises(ValidationError, match="label"):
        make_identity(label="validated")
    with pytest.raises(ValidationError, match="host"):
        Identity.model_validate({**make_identity().model_dump(), "host": "node12"})


def test_the_block_names_the_solution_key_the_request_and_the_solver():
    identity = Identity(
        case_id="island",
        sim_id="sim",
        attempt_id="att",
        hydromodpy_version="2.1.0",
        solution_key="sha256:solution",
        request_id="sha256:request",
        solver="modflow6",
    )

    assert identity.solution_key == "sha256:solution"
    assert identity.request_id == "sha256:request"
    assert identity.solver == "modflow6"
    assert "config_hash" not in Identity.model_fields


def test_a_block_of_a_pre_release_reads_without_the_key_that_left():
    block = {
        "case_id": "demo",
        "sim_id": "sim",
        "attempt_id": "att",
        "config_hash": "the solution key of a pre-release",
        "hydromodpy_version": "2.0.0",
    }

    identity = Identity.from_stored(block)

    assert identity.solution_key is None and identity.request_id is None
    assert identity.solver is None
    assert "config_hash" not in identity.model_dump()
