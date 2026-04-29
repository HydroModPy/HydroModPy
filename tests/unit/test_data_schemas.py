"""Unit tests for the pandera data contracts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.schemas import (
    DEMContract,
    validate_catchment,
    validate_dem,
    validate_lithology,
    validate_stations,
    validate_timeseries,
)


def test_timeseries_valid():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=3, freq="D"),
            "value": [1.0, 2.0, 3.0],
        }
    )
    out = validate_timeseries(df)
    assert {"date", "value"}.issubset(out.columns)


def test_timeseries_duplicate_date_fails():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "value": [1.0, 2.0],
        }
    )
    with pytest.raises(DataContractViolation):
        validate_timeseries(df)


def test_stations_valid():
    df = pd.DataFrame(
        {
            "station_id": ["A", "B"],
            "lat": [48.0, 49.0],
            "lon": [2.0, 3.0],
            "z": [100.0, 200.0],
            "name": ["One", "Two"],
        }
    )
    out = validate_stations(df)
    assert list(out["station_id"]) == ["A", "B"]
    assert {"lat", "lon", "z", "name"}.issubset(out.columns)


def test_stations_bad_lat_fails():
    df = pd.DataFrame(
        {
            "station_id": ["A"],
            "lat": [100.0],
            "lon": [2.0],
        }
    )
    with pytest.raises(DataContractViolation):
        validate_stations(df)


def test_lithology_valid():
    df = pd.DataFrame(
        {
            "zone_id": ["z1", "z2"],
            "conductivity": [1e-5, 2e-5],
            "porosity": [0.2, 0.3],
            "layer_thickness": [10.0, 15.0],
        }
    )
    out = validate_lithology(df)
    assert list(out["zone_id"]) == ["z1", "z2"]
    assert (out["conductivity"] > 0).all()


def test_lithology_negative_conductivity_fails():
    df = pd.DataFrame(
        {
            "zone_id": ["z1"],
            "conductivity": [-1.0],
        }
    )
    with pytest.raises(DataContractViolation):
        validate_lithology(df)


def test_dem_valid_numpy_dict():
    dem = {
        "data": np.ones((10, 10)) * 100.0,
        "resolution": (25.0, 25.0),
        "crs": "EPSG:2154",
    }
    out = validate_dem(dem)
    assert out["crs"] == "EPSG:2154"
    assert out["data"].shape == (10, 10)


def test_dem_missing_crs_fails():
    dem = {
        "data": np.ones((10, 10)),
        "resolution": 25.0,
        "crs": None,
    }
    with pytest.raises(DataContractViolation):
        validate_dem(dem)


def test_dem_resolution_out_of_range_fails():
    dem = {
        "data": np.ones((10, 10)),
        "resolution": 0.5,
        "crs": "EPSG:2154",
    }
    with pytest.raises(DataContractViolation):
        validate_dem(dem)


def test_catchment_requires_geodataframe():
    with pytest.raises(DataContractViolation):
        validate_catchment(object())


def test_catchment_valid():
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    gdf = gpd.GeoDataFrame(
        {"area_km2": [10.0]},
        geometry=[poly],
        crs="EPSG:2154",
    )
    out = validate_catchment(gdf)
    assert len(out) == 1
    assert str(out.crs) == "EPSG:2154"
    assert out.iloc[0]["area_km2"] == 10.0
