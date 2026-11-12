"""Pandera contracts of the data tables: timeseries, stations, lithology, catchment, abacus.

Each validator returns the frame when it holds and raises ``DataContractViolation``
otherwise. The abacus (stage m, volume m3, area m2) must have an increasing stage,
and the catchment is a GeoDataFrame with a CRS.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.schemas.abacus import validate_abacus
from hydromodpy.data.schemas.catchment import validate_catchment
from hydromodpy.data.schemas.lithology import validate_lithology
from hydromodpy.data.schemas.stations import validate_stations
from hydromodpy.data.schemas.timeseries import validate_timeseries


def good_abacus() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "lake_id": ["lac0", "lac0", "lac0"],
            "stage": [85.0, 87.0, 90.0],
            "volume": [0.0, 2.0e5, 1.2e6],
            "sarea": [0.0, 1.0e5, 4.0e5],
        }
    )


def non_monotone_abacus() -> pd.DataFrame:
    bad = good_abacus()
    bad.loc[2, "stage"] = 86.0  # breaks the increasing stage
    return bad


def unit_square_catchment() -> gpd.GeoDataFrame:
    square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    return gpd.GeoDataFrame({"area_km2": [10.0]}, geometry=[square], crs="EPSG:2154")


VALID = [
    pytest.param(
        validate_timeseries,
        pd.DataFrame(
            {"date": pd.date_range("2020-01-01", periods=3, freq="D"), "value": [1.0, 2.0, 3.0]}
        ),
        ["date", "value"],
        id="timeseries",
    ),
    pytest.param(
        validate_stations,
        pd.DataFrame(
            {
                "station_id": ["A", "B"],
                "lat": [48.0, 49.0],
                "lon": [2.0, 3.0],
                "z": [100.0, 200.0],
                "name": ["One", "Two"],
            }
        ),
        ["station_id", "lat", "lon", "z", "name"],
        id="stations",
    ),
    pytest.param(
        validate_lithology,
        pd.DataFrame(
            {
                "zone_id": ["z1", "z2"],
                "conductivity": [1e-5, 2e-5],  # m/s
                "porosity": [0.2, 0.3],
                "layer_thickness": [10.0, 15.0],  # m
            }
        ),
        ["zone_id", "conductivity", "porosity", "layer_thickness"],
        id="lithology",
    ),
    pytest.param(
        validate_abacus,
        good_abacus(),
        ["lake_id", "stage", "volume", "sarea"],
        id="abacus",
    ),
]


@pytest.mark.parametrize(("validate", "frame", "columns"), VALID)
def test_valid_table_is_returned(validate, frame, columns):
    out = validate(frame)

    assert set(columns).issubset(out.columns)
    pd.testing.assert_frame_equal(out[list(frame.columns)], frame, check_dtype=False)


def test_valid_catchment_is_returned():
    out = validate_catchment(unit_square_catchment())

    assert len(out) == 1
    assert str(out.crs) == "EPSG:2154"
    assert out.iloc[0]["area_km2"] == 10.0


REFUSALS = [
    pytest.param(
        validate_timeseries,
        pd.DataFrame({"date": pd.to_datetime(["2020-01-01", "2020-01-01"]), "value": [1.0, 2.0]}),
        id="duplicate date",
    ),
    pytest.param(
        validate_stations,
        pd.DataFrame({"station_id": ["A"], "lat": [100.0], "lon": [2.0]}),
        id="latitude out of range",
    ),
    pytest.param(
        validate_lithology,
        pd.DataFrame({"zone_id": ["z1"], "conductivity": [-1.0]}),
        id="negative conductivity",
    ),
    pytest.param(validate_catchment, object(), id="catchment is no GeoDataFrame"),
]


@pytest.mark.parametrize(("validate", "frame"), REFUSALS)
def test_refusals(validate, frame):
    with pytest.raises(DataContractViolation):
        validate(frame)


def test_non_monotone_stage_names_the_column():
    with pytest.raises(DataContractViolation) as exc:
        validate_abacus(non_monotone_abacus())

    assert "stage" in str(exc.value.context["failures"]).lower()
