"""The lake readers match a result's records to lake ids: polygons, stage-volume tables and bathymetry rasters."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from hydromodpy.data.variables.lake_abacus.read import lake_abacus
from hydromodpy.data.variables.lake_bathymetry.read import lake_bathymetry
from hydromodpy.data.variables.lake_geometry.read import lake_polygons


def test_polygons_by_lake_id(tmp_path: Path) -> None:
    poly_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    poly_b = Polygon([(20, 20), (30, 20), (30, 30), (20, 30)])
    path = tmp_path / "lakes.parquet"
    gpd.GeoDataFrame(
        {"lake_id": ["lake_a", "lake_b"]}, geometry=[poly_a, poly_b], crs="EPSG:2154"
    ).to_parquet(path)

    polys = lake_polygons(
        SimpleNamespace(fields=[SimpleNamespace(data=str(path))]), lake_ids=["lake_a", "lake_b"]
    )

    assert polys["lake_a"].equals(poly_a)
    assert polys["lake_b"].equals(poly_b)


def test_a_single_polygon_needs_no_id_column(tmp_path: Path) -> None:
    poly = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    path = tmp_path / "lake_single.parquet"
    gpd.GeoDataFrame(geometry=[poly], crs="EPSG:2154").to_parquet(path)

    polys = lake_polygons(
        SimpleNamespace(fields=[SimpleNamespace(data=str(path))]), lake_ids=["reservoir"]
    )

    assert polys["reservoir"].equals(poly)


def test_abacus_by_lake_id(tmp_path: Path) -> None:
    path = tmp_path / "abacus.parquet"
    pd.DataFrame(
        {
            "lake_id": ["lake_1", "lake_1", "lake_2", "lake_2"],
            "stage": [1.0, 2.0, 10.0, 20.0],
            "volume": [10.0, 20.0, 100.0, 200.0],
            "sarea": [5.0, 5.0, 50.0, 50.0],
        }
    ).to_parquet(path)

    abacus_map = lake_abacus(
        SimpleNamespace(tables=[SimpleNamespace(data=str(path))]), lake_ids=["lake_1", "lake_2"]
    )

    assert abacus_map["lake_1"]["stage"] == [1.0, 2.0]
    assert abacus_map["lake_2"]["stage"] == [10.0, 20.0]


def test_a_single_abacus_is_matched_by_table_id(tmp_path: Path) -> None:
    path = tmp_path / "abacus_lone.parquet"
    pd.DataFrame({"stage": [5.0, 6.0], "volume": [50.0, 60.0], "sarea": [25.0, 25.0]}).to_parquet(
        path
    )
    record = SimpleNamespace(data=str(path), table_id="reservoir")

    abacus_map = lake_abacus(SimpleNamespace(tables=[record]), lake_ids=["reservoir"])

    assert abacus_map["reservoir"]["stage"] == [5.0, 6.0]


def test_a_single_bathymetry_record_serves_the_lake() -> None:
    result = SimpleNamespace(fields=[SimpleNamespace(data="/path/to/bathy.tif")])

    assert lake_bathymetry(result, lake_ids=["lake_only"]) == {
        "lake_only": Path("/path/to/bathy.tif")
    }


def test_bathymetry_is_matched_by_the_lake_id_in_the_name() -> None:
    names = ["/path/to/lake_bathymetry_custom_lac0.tif", "/path/to/lake_bathymetry_custom_lac1.tif"]
    result = SimpleNamespace(fields=[SimpleNamespace(data=name) for name in names])

    matched = lake_bathymetry(result, lake_ids=["lac0", "lac1"])

    assert matched == {"lac0": Path(names[0]), "lac1": Path(names[1])}


NOTHING = [
    pytest.param(lake_polygons, None, id="polygons none"),
    pytest.param(lake_polygons, SimpleNamespace(fields=[]), id="polygons empty"),
    pytest.param(lake_abacus, None, id="abacus none"),
    pytest.param(lake_abacus, SimpleNamespace(tables=[]), id="abacus empty"),
    pytest.param(lake_bathymetry, None, id="bathymetry none"),
    pytest.param(lake_bathymetry, SimpleNamespace(fields=[]), id="bathymetry empty"),
]


@pytest.mark.parametrize(("reader", "result"), NOTHING)
def test_no_record_gives_an_empty_map(reader, result) -> None:
    assert reader(result, lake_ids=["lake_a"]) == {}
