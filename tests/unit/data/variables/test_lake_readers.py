"""Unit tests for the lake data readers (geometry, abacus, bathymetry)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

from hydromodpy.data.variables.lake_abacus.read import lake_abacus
from hydromodpy.data.variables.lake_bathymetry.read import lake_bathymetry
from hydromodpy.data.variables.lake_geometry.read import lake_polygons


def test_lake_polygons_matches_by_lake_id(tmp_path: Path) -> None:
    poly_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    poly_b = Polygon([(20, 20), (30, 20), (30, 30), (20, 30)])
    gdf = gpd.GeoDataFrame(
        {"lake_id": ["lake_a", "lake_b"]},
        geometry=[poly_a, poly_b],
        crs="EPSG:2154",
    )
    parquet_path = tmp_path / "lakes.parquet"
    gdf.to_parquet(parquet_path)

    result = SimpleNamespace(fields=[SimpleNamespace(data=str(parquet_path))])
    polys = lake_polygons(result, lake_ids=["lake_a", "lake_b"])

    assert "lake_a" in polys and "lake_b" in polys
    assert polys["lake_a"].equals(poly_a)
    assert polys["lake_b"].equals(poly_b)


def test_lake_polygons_matches_single_lake_without_column(tmp_path: Path) -> None:
    poly = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    gdf = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:2154")
    parquet_path = tmp_path / "lake_single.parquet"
    gdf.to_parquet(parquet_path)

    result = SimpleNamespace(fields=[SimpleNamespace(data=str(parquet_path))])
    polys = lake_polygons(result, lake_ids=["reservoir"])

    assert "reservoir" in polys
    assert polys["reservoir"].equals(poly)


def test_lake_polygons_returns_empty_when_none_or_empty() -> None:
    assert lake_polygons(None, lake_ids=["lake_a"]) == {}
    assert lake_polygons(SimpleNamespace(fields=[]), lake_ids=["lake_a"]) == {}


def test_lake_abacus_matches_by_lake_id(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "lake_id": ["lake_1", "lake_1", "lake_2", "lake_2"],
            "stage": [1.0, 2.0, 10.0, 20.0],
            "volume": [10.0, 20.0, 100.0, 200.0],
            "sarea": [5.0, 5.0, 50.0, 50.0],
        }
    )
    parquet_path = tmp_path / "abacus.parquet"
    df.to_parquet(parquet_path)

    result = SimpleNamespace(tables=[SimpleNamespace(data=str(parquet_path))])
    abacus_map = lake_abacus(result, lake_ids=["lake_1", "lake_2"])

    assert "lake_1" in abacus_map and "lake_2" in abacus_map
    assert abacus_map["lake_1"]["stage"] == [1.0, 2.0]
    assert abacus_map["lake_2"]["stage"] == [10.0, 20.0]


def test_lake_abacus_matches_single_lake_with_table_id(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "stage": [5.0, 6.0],
            "volume": [50.0, 60.0],
            "sarea": [25.0, 25.0],
        }
    )
    parquet_path = tmp_path / "abacus_lone.parquet"
    df.to_parquet(parquet_path)

    record = SimpleNamespace(data=str(parquet_path), table_id="reservoir")
    result = SimpleNamespace(tables=[record])
    abacus_map = lake_abacus(result, lake_ids=["reservoir"])

    assert "reservoir" in abacus_map
    assert abacus_map["reservoir"]["stage"] == [5.0, 6.0]


def test_lake_abacus_returns_empty_when_none_or_empty() -> None:
    assert lake_abacus(None, lake_ids=["lake_1"]) == {}
    assert lake_abacus(SimpleNamespace(tables=[]), lake_ids=["lake_1"]) == {}


def test_lake_bathymetry_matches_single_record() -> None:
    result = SimpleNamespace(fields=[SimpleNamespace(data="/path/to/bathy.tif")])
    matched = lake_bathymetry(result, lake_ids=["lake_only"])
    assert matched == {"lake_only": Path("/path/to/bathy.tif")}


def test_lake_bathymetry_matches_stem_containment() -> None:
    records = [
        SimpleNamespace(data="/path/to/lake_bathymetry_custom_lac0.tif"),
        SimpleNamespace(data="/path/to/lake_bathymetry_custom_lac1.tif"),
    ]
    matched = lake_bathymetry(SimpleNamespace(fields=records), lake_ids=["lac0", "lac1"])
    assert matched["lac0"] == Path("/path/to/lake_bathymetry_custom_lac0.tif")
    assert matched["lac1"] == Path("/path/to/lake_bathymetry_custom_lac1.tif")


def test_lake_bathymetry_returns_empty_when_none_or_empty() -> None:
    assert lake_bathymetry(None, lake_ids=["lac0"]) == {}
    assert lake_bathymetry(SimpleNamespace(fields=[]), lake_ids=["lac0"]) == {}
