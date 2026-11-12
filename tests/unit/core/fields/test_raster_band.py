"""One band written on a borrowed profile, and the cells that hold a value."""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.transform import from_origin

from hydromodpy.core.fields.nodata import valid_cells

PROFILE = {
    "driver": "GTiff",
    "height": 2,
    "width": 3,
    "count": 3,
    "dtype": "float32",
    "transform": from_origin(0.0, 50.0, 25.0, 25.0),
    "nodata": -9999.0,
}


@pytest.mark.parametrize(
    ("values", "nodata", "expected"),
    [
        ([1.0, np.nan, -9999.0, np.inf], -9999.0, [True, False, False, False]),
        ([1.0, np.nan], float("nan"), [True, False]),
        ([1, 0], None, [True, True]),
    ],
    ids=["sentinel", "nan-sentinel", "no-sentinel"],
)
def test_a_cell_holds_a_value_when_finite_and_not_the_sentinel(
    values: list[float], nodata: float | None, expected: list[bool]
) -> None:
    np.testing.assert_array_equal(valid_cells(np.asarray(values), nodata), expected)
