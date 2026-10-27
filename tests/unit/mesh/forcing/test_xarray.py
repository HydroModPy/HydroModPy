"""A gridded forcing read from a dataset, a NetCDF or a GeoTIFF, :mod:`hydromodpy.spatial.mesh.forcing._xarray`."""

from __future__ import annotations

import warnings
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.spatial.mesh.forcing import discretize_fields_on_cells
from hydromodpy.spatial.mesh.forcing._xarray import discretize_from_xarray
from tests.unit.mesh.forcing.forcing_cases import (
    MM_DAY_TO_M_S,
    centres,
    daily_field,
    field_record,
    grid_dataset,
    pixel_axes,
    static_field,
    window,
    write_geotiff,
)

pytestmark = pytest.mark.fast


def _on_cells(record, nrow: int, ncol: int, nper: int, simulation_window=None):
    return discretize_fields_on_cells(
        load_result=LoadResult(fields=[record]),
        centers=centres(nrow, ncol),
        nper=nper,
        simulation_window=simulation_window,
    )


def _rate(array: np.ndarray) -> float:
    """The uniform rate of *array*, in mm/day."""
    assert np.ptp(array) == pytest.approx(0.0, abs=1e-15)
    return float(array[0]) / MM_DAY_TO_M_S


def test_a_static_grid_gives_the_same_rate_to_every_period():
    result = _on_cells(static_field(4, 5, 5.0), 4, 5, nper=3)

    assert sorted(result) == [0, 1, 2]
    for kper in range(3):
        assert result[kper].shape == (20,)
        np.testing.assert_allclose(result[kper], 5.0 * MM_DAY_TO_M_S, rtol=1e-10)


@pytest.mark.parametrize(
    ("values_per_day", "end", "expected"),
    [
        ([float(day + 1) for day in range(31)], "2020-01-31", [16.0]),
        ([10.0] * 31 + [20.0] * 29, "2020-02-29", [10.0, 20.0]),
    ],
    ids=["january-rising", "january-then-february"],
)
def test_a_daily_grid_takes_the_mean_of_its_days_in_each_period(values_per_day, end, expected):
    record = daily_field(2, 3, values_per_day)

    result = _on_cells(
        record, 2, 3, nper=len(expected), simulation_window=window("2020-01-01", end)
    )

    assert sorted(result) == list(range(len(expected)))
    for kper, rate in enumerate(expected):
        assert result[kper].shape == (6,)
        assert _rate(result[kper]) == pytest.approx(rate, rel=1e-6)


def test_a_period_after_the_last_slice_takes_that_slice_under_ignore():
    record = daily_field(2, 2, [5.0] * 9 + [7.0])

    result = _on_cells(record, 2, 2, nper=3, simulation_window=window("2020-01-01", "2020-03-31"))

    assert _rate(result[0]) == pytest.approx(5.2)
    assert _rate(result[1]) == pytest.approx(7.0)
    assert _rate(result[2]) == pytest.approx(7.0)


def test_a_grid_gap_takes_the_slice_in_force_not_the_nearest_one():
    # Daily slices on 6-hour periods: 18:00 is nearer to the next day's slice,
    # but the slice in force is the one of its own day.
    six_hours = window("2020-01-01", "2020-01-02 23:00", 6, "hour", coverage_policy="error")

    result = _on_cells(daily_field(1, 1, [1.0, 3.0]), 1, 1, nper=8, simulation_window=six_hours)

    np.testing.assert_allclose([_rate(result[k]) for k in range(8)], [1.0] * 4 + [3.0] * 4)


def test_without_a_window_each_slice_is_one_period():
    result = _on_cells(daily_field(2, 2, [1.0, 3.0, 5.0]), 2, 2, nper=3)

    np.testing.assert_allclose([_rate(result[k]) for k in range(3)], [1.0, 3.0, 5.0])


def test_a_grid_with_an_empty_time_axis_and_no_window_gives_no_period():
    x, y = pixel_axes(2, 2)
    times = pd.DatetimeIndex([], dtype="datetime64[ns]")
    dataset = grid_dataset(np.zeros((0, 2, 2)), x, y, times)

    result = discretize_from_xarray(
        dataset, centers=centres(2, 2), nper=2, period_bounds=None, unit_factor=1.0
    )

    assert result == {}


def test_a_dataset_without_a_data_variable_gives_zero_on_every_period():
    result = _on_cells(field_record(xr.Dataset()), 2, 2, nper=2)

    assert sorted(result) == [0, 1]
    assert all(np.all(result[kper] == 0.0) for kper in range(2))


def _with_nodata(values: np.ndarray) -> np.ndarray:
    values = np.array(values, dtype=float)
    values.reshape(-1)[1] = np.nan
    return values


@pytest.mark.parametrize(
    ("record", "simulation_window", "match"),
    [
        (
            field_record(grid_dataset(_with_nodata(np.ones((2, 2))), *pixel_axes(2, 2))),
            None,
            r"recharge gridded forcing values must contain only finite numeric values",
        ),
        (
            field_record(grid_dataset(np.ones((2, 0)), np.zeros(0), pixel_axes(2, 2)[1])),
            None,
            r"recharge gridded forcing values cannot be empty",
        ),
        (
            field_record(
                grid_dataset(
                    _with_nodata(np.ones((3, 2, 2))),
                    *pixel_axes(2, 2),
                    pd.date_range("2020-01-01", periods=3, freq="D"),
                ),
                days=3,
            ),
            window("2020-01-01", "2020-01-31"),
            r"values for stress period 0 must contain only finite numeric values",
        ),
        (
            field_record(
                grid_dataset(
                    _with_nodata(np.ones((3, 2, 2))),
                    *pixel_axes(2, 2),
                    pd.date_range("2020-01-01", periods=3, freq="D"),
                ),
                days=3,
            ),
            None,
            r"values for stress period 0 must contain only finite numeric values",
        ),
    ],
    ids=[
        "static-nodata-pixel",
        "static-clipped-to-nothing",
        "daily-nodata-pixel",
        "daily-nodata-pixel-no-window",
    ],
)
def test_a_grid_with_a_nodata_pixel_or_no_pixel_is_refused(record, simulation_window, match):
    with pytest.raises(ValueError, match=match):
        _on_cells(record, 2, 2, nper=1, simulation_window=simulation_window)


def test_a_single_band_geotiff_gives_its_rate_to_every_period(tmp_path: Path):
    x, y = pixel_axes(4, 5)
    path = write_geotiff(tmp_path / "recharge.tif", np.full((1, 4, 5), 8.0), x, y, "float32")

    result = _on_cells(field_record(path), 4, 5, nper=2)

    assert sorted(result) == [0, 1]
    for kper in range(2):
        assert result[kper].shape == (20,)
        assert _rate(result[kper]) == pytest.approx(8.0, rel=1e-4)


def test_a_static_netcdf_gives_its_rate(tmp_path: Path):
    path = tmp_path / "recharge.nc"
    grid_dataset(np.full((3, 4), 6.0), *pixel_axes(3, 4)).to_netcdf(path)

    result = _on_cells(field_record(path), 3, 4, nper=1)

    assert result[0].shape == (12,)
    assert _rate(result[0]) == pytest.approx(6.0, rel=1e-4)


def test_a_daily_netcdf_takes_the_mean_of_its_days(tmp_path: Path):
    path = tmp_path / "recharge_temporal.nc"
    times = pd.date_range("2020-01-01", periods=31, freq="D")
    grid_dataset(np.full((31, 2, 3), 4.0), *pixel_axes(2, 3), times).to_netcdf(path)

    result = _on_cells(
        field_record(path, days=31),
        2,
        3,
        nper=1,
        simulation_window=window("2020-01-01", "2020-01-31"),
    )

    assert result[0].shape == (6,)
    assert _rate(result[0]) == pytest.approx(4.0, rel=1e-4)


def _bands(rates: list[float], nrow: int = 3, ncol: int = 4) -> np.ndarray:
    return np.asarray(rates, dtype=float)[:, None, None] * np.ones((len(rates), nrow, ncol))


def test_a_multi_band_geotiff_without_window_gives_one_band_per_period(tmp_path: Path):
    rates = [2.0, 4.0, 6.0]
    path = write_geotiff(
        tmp_path / "recharge_multi.tif", _bands(rates), *pixel_axes(3, 4), "float32"
    )

    result = _on_cells(field_record(path), 3, 4, nper=3)

    assert sorted(result) == [0, 1, 2]
    assert [_rate(result[k]) for k in range(3)] == pytest.approx(rates, rel=1e-4)


def test_a_multi_band_geotiff_shares_its_bands_among_the_periods(tmp_path: Path):
    path = write_geotiff(tmp_path / "recharge.tif", _bands([2.0, 4.0, 6.0, 8.0]), *pixel_axes(3, 4))

    result = _on_cells(
        field_record(path), 3, 4, nper=2, simulation_window=window("2020-01-01", "2020-02-29")
    )

    assert [_rate(result[k]) for k in range(2)] == pytest.approx([3.0, 7.0])


@pytest.mark.parametrize(
    ("policy", "expectation"),
    [
        ("ignore", nullcontext()),
        (
            "warn",
            pytest.warns(UserWarning, match="no GeoTIFF forcing band mapped to stress period 2"),
        ),
    ],
    ids=["ignore", "warn"],
)
def test_a_period_no_band_reaches_takes_the_last_band(tmp_path: Path, policy, expectation):
    path = write_geotiff(tmp_path / "recharge.tif", _bands([2.0, 4.0]), *pixel_axes(3, 4))
    three_months = window("2020-01-01", "2020-03-31", coverage_policy=policy)

    with expectation, warnings.catch_warnings():
        if policy == "ignore":
            warnings.simplefilter("error", UserWarning)
        result = _on_cells(field_record(path), 3, 4, nper=3, simulation_window=three_months)

    assert [_rate(result[k]) for k in range(3)] == pytest.approx([2.0, 4.0, 4.0])


def test_a_period_no_band_reaches_stops_the_run_under_error(tmp_path: Path):
    path = write_geotiff(tmp_path / "recharge.tif", _bands([2.0, 4.0]), *pixel_axes(3, 4))
    three_months = window("2020-01-01", "2020-03-31", coverage_policy="error")

    with pytest.raises(ValueError, match="no GeoTIFF forcing band mapped to stress period 2"):
        _on_cells(field_record(path), 3, 4, nper=3, simulation_window=three_months)
