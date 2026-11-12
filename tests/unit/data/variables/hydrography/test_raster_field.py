"""The stream raster takes numbers: a numeric column is kept, a text column is numbered from one."""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.data.variables.hydrography.variable import numeric_raster_field

FIELDS = [
    pytest.param({"FID": ["3", "7"]}, "FID", [3, 7], id="numeric column"),
    pytest.param({"code": ["04A0000", "04B0001", "04C0002"]}, "code", [1, 2, 3], id="text column"),
]


@pytest.mark.parametrize(("columns", "field", "expected"), FIELDS)
def test_numeric_raster_field(columns, field, expected):
    assert numeric_raster_field(pd.DataFrame(columns), field).tolist() == expected
