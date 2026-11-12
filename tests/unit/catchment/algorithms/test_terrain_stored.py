"""The terrain product codec: write three rasters and terrain.json, read them back."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio

from hydromodpy.catchment.algorithms.flow_products import FlowProducts, TerrainRequest
from hydromodpy.catchment.algorithms.terrain_stored import (
    SCHEMA_VERSION,
    read_terrain,
    write_terrain,
)
from hydromodpy.catchment.terrain.port import (
    CappedBreach,
    CappedBreachReport,
    ConditionedDem,
    ConditioningExtent,
    DrainageDirections,
    FlowAccumulation,
)
from hydromodpy.catchment.terrain.undrained import UndrainedCells
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.terrain_doubles import fake_accumulation


def _write_stack(directory: Path, *, method: str = "fill") -> tuple[FlowProducts, Path, Path, Path]:
    correc = directory / f"dem_{method}.tif"
    direc = directory / "dem_direc.tif"
    acc = directory / "dem_acc.tif"
    write_geotiff(correc, np.full((6, 6), 100.0, dtype=np.float32), cell=25.0, nodata=-9999.0)
    write_geotiff(direc, np.full((6, 6), 1, dtype=np.int16), cell=25.0, nodata=-32768)
    write_geotiff(acc, np.full((6, 6), 2.0, dtype=np.float32), cell=25.0, nodata=-32768.0)
    products = FlowProducts(
        accumulation=fake_accumulation(correc=correc, direc=direc, acc=acc, method=method),
        undrained=UndrainedCells(without_descent=2, strict_pits=1),
    )
    return products, correc, direc, acc


def _request(method: str, out_dir: Path, dem: Path = Path("source.tif")) -> TerrainRequest:
    return TerrainRequest(
        dem=dem,
        dem_sha256="a" * 64,
        state="raw",
        method=method,
        capped_breach=None,
        crs_project=None,
        engine={"engine_id": "whitebox_workflows", "engine_version": "1.0.0"},
        notched=False,
        out_dir=out_dir,
    )


def test_a_stack_without_counts_writes_null_not_zeros(tmp_path) -> None:
    store = tmp_path / "store"
    products, *_ = _write_stack(tmp_path / "built")

    write_terrain(FlowProducts(accumulation=products.accumulation), store)
    restored = read_terrain(store, _request("fill", tmp_path / "out"))

    document = json.loads((store / "terrain.json").read_text(encoding="utf-8"))
    assert document["undrained"] is None
    assert restored.undrained is None


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(lambda doc, store: doc.update(schema="other.v0"), id="another_format"),
        pytest.param(lambda doc, store: doc.pop("undrained"), id="a_missing_key"),
        pytest.param(
            lambda doc, store: doc["files"]["acc"].update(bytes=1), id="a_size_that_differs"
        ),
        pytest.param(
            lambda doc, store: doc.update(undrained={"pits": 1}), id="counts_of_another_shape"
        ),
    ],
)
def test_a_damaged_product_is_refused_so_the_store_rebuilds_it(tmp_path, damage) -> None:
    store = tmp_path / "store"
    products, *_ = _write_stack(tmp_path / "built")
    write_terrain(products, store)
    document = json.loads((store / "terrain.json").read_text(encoding="utf-8"))
    damage(document, store)
    (store / "terrain.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable"):
        read_terrain(store, _request("fill", tmp_path / "out"))


def test_a_restored_raster_is_uncompressed_and_equal_in_values(tmp_path) -> None:
    store = tmp_path / "store"
    out = tmp_path / "out"
    products, correc, *_ = _write_stack(tmp_path / "built")

    write_terrain(products, store)
    read_terrain(store, _request("fill", out))

    with rasterio.open(str(store / correc.name)) as stored:
        assert stored.compression is not None
    with rasterio.open(str(out / correc.name)) as restored:
        assert restored.compression is None
        restored_values = restored.read(1)
    with rasterio.open(str(correc)) as built:
        np.testing.assert_array_equal(built.read(1), restored_values)


def test_a_provided_stack_reads_back_without_a_conditioning_method(tmp_path) -> None:
    store = tmp_path / "store"
    out = tmp_path / "out"
    products, source, _, _ = _write_stack(tmp_path / "built", method="provided")

    write_terrain(products, store)
    restored = read_terrain(store, _request("provided", out, dem=source))

    assert restored.accumulation.directions.conditioned_dem.method == "provided"
    assert restored.correc == str(source)
    assert not (store / source.name).exists()
    document = json.loads((store / "terrain.json").read_text(encoding="utf-8"))
    assert document["conditioned_name"] is None
    assert sorted(document["files"]) == ["acc", "direc"]


def test_a_capped_breach_report_survives_the_round_trip(tmp_path) -> None:
    store = tmp_path / "store"
    out = tmp_path / "out"
    correc = tmp_path / "built" / "dem_capped_breach.tif"
    direc = tmp_path / "built" / "dem_direc.tif"
    acc = tmp_path / "built" / "dem_acc.tif"
    write_geotiff(correc, np.full((6, 6), 100.0, dtype=np.float32), cell=25.0, nodata=-9999.0)
    write_geotiff(direc, np.full((6, 6), 1, dtype=np.int16), cell=25.0, nodata=-32768)
    write_geotiff(acc, np.full((6, 6), 2.0, dtype=np.float32), cell=25.0, nodata=-32768.0)
    report = CappedBreachReport(
        cells_lowered=7,
        cells_raised=3,
        max_lowering_m=1.5,
        max_raise_m=0.5,
        max_dist_cells=12,
        max_cost_m=2.0,
        move_threshold_m=0.01,
    )
    conditioned = ConditionedDem(
        path=correc,
        method=CappedBreach(max_depth_m=2.0, max_distance_m=50.0),
        extent=ConditioningExtent.regional(),
        crs="EPSG:2154",
        breach_report=report,
    )
    products = FlowProducts(
        accumulation=FlowAccumulation(
            path=acc,
            units="cells",
            transform="ln",
            directions=DrainageDirections(
                path=direc,
                pointer_convention="d8_wbt",
                conditioned_dem=conditioned,
            ),
            nodata=-32768.0,
        ),
        undrained=UndrainedCells(without_descent=0, strict_pits=0),
    )
    request = TerrainRequest(
        dem=Path("source.tif"),
        dem_sha256="a" * 64,
        state="raw",
        method="capped_breach",
        capped_breach=CappedBreach(max_depth_m=2.0, max_distance_m=50.0),
        crs_project=None,
        engine={"engine_id": "whitebox_workflows", "engine_version": "1.0.0"},
        notched=False,
        out_dir=out,
    )

    write_terrain(products, store)
    restored = read_terrain(store, request)

    restored_report = restored.accumulation.directions.conditioned_dem.breach_report
    assert restored_report == report


def test_an_unreadable_terrain_json_is_refused(tmp_path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "terrain.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable"):
        read_terrain(store, _request("fill", tmp_path / "out"))


def test_schema_version_names_the_codec() -> None:
    assert SCHEMA_VERSION == "hydromodpy.terrain_product.v1"
