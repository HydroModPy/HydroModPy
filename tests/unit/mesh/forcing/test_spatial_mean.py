"""The mean of a gridded forcing over its pixels, :mod:`hydromodpy.spatial.mesh.forcing._spatial_mean`.

A gridded record reduces to one value per date when the run asks for a
homogeneous forcing. The series stays in the unit of the record.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.spatial.mesh.forcing import spatial_mean_from_fields
from tests.unit.mesh.forcing.forcing_cases import (
    daily_field,
    field_record,
    grid_dataset,
    pixel_axes,
    static_field,
    write_geotiff,
)

pytestmark = pytest.mark.fast


def _mean(record) -> pd.Series:
    return spatial_mean_from_fields(LoadResult(fields=[record]))


def test_a_static_grid_has_one_mean_value():
    series = _mean(static_field(3, 4, 7.5))

    assert len(series) == 1
    assert series.iloc[0] == pytest.approx(7.5, rel=1e-10)


def test_a_daily_grid_has_one_mean_a_day():
    series = _mean(daily_field(2, 3, [1.0, 2.0, 3.0]))

    assert list(series.index) == list(pd.date_range("2020-01-01", periods=3, freq="D"))
    np.testing.assert_allclose(series.to_numpy(), [1.0, 2.0, 3.0], rtol=1e-10)


def _ramp(nrow: int = 2, ncol: int = 3) -> np.ndarray:
    """A grid whose pixels hold 0 to 5 mm/day, mean 2.5."""
    return np.arange(nrow * ncol, dtype=float).reshape(nrow, ncol)


@pytest.mark.parametrize("daily", [False, True], ids=["static", "daily"])
def test_a_netcdf_file_has_the_mean_of_the_grid_it_holds(tmp_path: Path, daily):
    x, y = pixel_axes(2, 3)
    path = tmp_path / "recharge.nc"
    if daily:
        times = pd.date_range("2020-01-01", periods=2, freq="D")
        grid_dataset(np.stack([_ramp(), 2.0 * _ramp()]), x, y, times).to_netcdf(path)
    else:
        grid_dataset(_ramp(), x, y).to_netcdf(path)

    series = _mean(field_record(path, days=2 if daily else None))

    np.testing.assert_allclose(series.to_numpy(), [2.5, 5.0] if daily else [2.5])


def test_a_geotiff_file_has_the_mean_of_its_first_band(tmp_path: Path):
    path = write_geotiff(tmp_path / "recharge.tif", _ramp()[None], *pixel_axes(2, 3))

    series = _mean(field_record(str(path)))

    np.testing.assert_allclose(series.to_numpy(), [2.5])


def _nodata_grid() -> np.ndarray:
    values = _ramp()
    values[0, 1] = np.nan
    return values


@pytest.mark.parametrize(
    ("record", "match"),
    [
        (
            field_record(grid_dataset(_nodata_grid(), *pixel_axes(2, 3))),
            "recharge gridded forcing values must contain only finite numeric values",
        ),
        (
            field_record(grid_dataset(np.ones((2, 0)), np.zeros(0), pixel_axes(2, 3)[1])),
            "recharge gridded forcing values cannot be empty",
        ),
    ],
    ids=["a-nodata-pixel", "clipped-to-nothing"],
)
def test_a_grid_with_a_nodata_pixel_or_no_pixel_has_no_mean(record, match):
    with pytest.raises(ValueError, match=match):
        _mean(record)


def test_a_geotiff_with_a_nodata_pixel_has_no_mean(tmp_path: Path):
    path = write_geotiff(tmp_path / "recharge.tif", _nodata_grid()[None], *pixel_axes(2, 3))

    with pytest.raises(
        ValueError, match="recharge GeoTIFF forcing values must contain only finite"
    ):
        _mean(field_record(path))
