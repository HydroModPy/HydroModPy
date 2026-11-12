"""Zone codes of a geology map: key normalisation, integer encoding of a raster,
sea override on a land-sea mask and sea zones of a polygon table.

Rasters are dimensionless zone codes. Nothing here has a unit.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.data.variables.geology import processing as proc

NORMALIZED_KEYS = [
    pytest.param(12, "12", id="int"),
    pytest.param(np.int64(3), "3", id="numpy int"),
    pytest.param(12.0, "12", id="whole float"),
    pytest.param(12.5, "12.5", id="fractional float"),
    pytest.param(np.float32(4.0), "4", id="numpy float"),
    pytest.param(float("nan"), "nan", id="nan"),
    pytest.param("  A31 ", "A31", id="padded text"),
]


@pytest.mark.parametrize(("raw", "expected"), NORMALIZED_KEYS)
def test_normalize_zone_key(raw, expected):
    assert proc.normalize_zone_key(raw) == expected


def test_encode_numeric_raster_skips_nodata_and_nan():
    raw = np.array([[5.0, 5.0, np.nan], [-1.0, 2.0, 2.0]])

    codes, mapping = proc.encode_numeric_raster(raw, nodata_value=-1)

    assert codes.dtype == np.int32
    assert codes.tolist() == [[2, 2, 0], [0, 1, 1]]
    assert mapping == {1: "2", 2: "5"}


def test_encode_numeric_raster_all_invalid():
    codes, mapping = proc.encode_numeric_raster(np.full((2, 2), np.nan))

    assert not codes.any()
    assert mapping == {}


# Land-sea mask: 0 is land, 1 is sea, nan is outside the mask.
CODES = np.array([[1, 2], [1, 2]])
SEA = np.array([[0.0, 1.0], [np.nan, 1.0]])
ZONES = {1: "A", 2: "B"}


def test_landsea_override_adds_a_zone():
    out, mapping = proc.apply_landsea_override(CODES, encoded_to_zone=ZONES, landsea_array=SEA)

    assert out.tolist() == [[3, 2], [1, 2]]
    assert mapping == {1: "A", 2: "B", 3: "1"}
    assert CODES.tolist() == [[1, 2], [1, 2]]  # the input is not changed


def test_landsea_override_reuses_a_zone():
    out, mapping = proc.apply_landsea_override(
        CODES, encoded_to_zone=ZONES, landsea_array=SEA, override_zone_key="B"
    )

    assert out.tolist() == [[2, 2], [1, 2]]
    assert mapping == ZONES


def test_landsea_override_without_sea_cell():
    out, mapping = proc.apply_landsea_override(
        np.array([[1, 2]]), encoded_to_zone={1: "A"}, landsea_array=np.array([[5.0, 5.0]])
    )

    assert out.tolist() == [[1, 2]]
    assert mapping == {1: "A"}


@pytest.fixture
def zone_table():
    return gpd.GeoDataFrame(
        {"zone_key": ["a", "b", "c"], "kind": ["land", " Sea ", "SEA"]},
        geometry=[box(0, 0, 1, 1)] * 3,
    )


SEA_ZONES = [
    pytest.param({"enabled": False}, "disabled", id="disabled"),
    pytest.param({"zone_key_column": "nope"}, "missing_zone_key_column:nope", id="no key column"),
    pytest.param({"zone_key_column": " "}, "missing_zone_key_column:", id="blank key column"),
    pytest.param({"sea_field": "nofield"}, "missing_field:nofield", id="no sea field"),
    pytest.param({"sea_value": "lake"}, "no_matching_sea_polygon", id="no sea polygon"),
    pytest.param({}, "ok", id="two sea polygons"),
]


@pytest.mark.parametrize(("kwargs", "reason"), SEA_ZONES)
def test_uniformize_sea_zone(zone_table, kwargs, reason):
    args = {"sea_field": "kind", "sea_value": "sea", "sea_zone_key": "SEA"} | kwargs

    out, info = proc.uniformize_sea_zone_on_dataframe(zone_table, **args)

    applied = reason == "ok"
    assert info["applied"] is applied
    assert info["reason"] == reason
    assert out["zone_key"].tolist() == (["a", "SEA", "SEA"] if applied else ["a", "b", "c"])
    assert info["count"] == (2 if applied else 0)


def test_refusals():
    with pytest.raises(ValueError, match="2D array"):
        proc.encode_numeric_raster(np.ones(3))
    with pytest.raises(ValueError, match="must match encoded_codes shape"):
        proc.apply_landsea_override(
            np.array([[1, 2]]), encoded_to_zone={}, landsea_array=np.zeros((2, 2))
        )
