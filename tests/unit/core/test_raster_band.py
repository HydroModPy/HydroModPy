"""One band written on a borrowed profile, and the cells that hold a value."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.core.io.raster_io import write_band
from hydromodpy.core.nodata import valid_cells

PROFILE = {
    "driver": "GTiff",
    "height": 2,
    "width": 3,
    "count": 3,
    "dtype": "float32",
    "transform": from_origin(0.0, 50.0, 25.0, 25.0),
    "nodata": -9999.0,
}


def test_a_band_is_written_on_a_copy_of_the_profile_with_its_crs(tmp_path: Path) -> None:
    values = np.arange(6, dtype="uint8").reshape(2, 3)
    out = write_band(
        tmp_path / "deep" / "zones.tif", values, PROFILE, crs="EPSG:2154", dtype="uint8", nodata=0
    )
    with rasterio.open(out) as src:
        assert (src.count, src.dtypes[0], src.nodata) == (1, "uint8", 0.0)
        assert src.crs.to_epsg() == 2154
        np.testing.assert_array_equal(src.read(1), values)
    assert PROFILE["count"] == 3 and PROFILE["dtype"] == "float32"


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
