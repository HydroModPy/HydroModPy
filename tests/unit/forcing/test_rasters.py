"""A gridded forcing read from a dataset, a NetCDF or a GeoTIFF, :mod:`hydromodpy.spatial.forcing.rasters`.

The nodata tests read the 3 x 3 cells of ``centres`` on a raster with one more
row at the north and one more column at the east, so its north-east pixel lies
beyond every cell. The spatial mean reduces a grid to one value per date when
the run asks for a homogeneous forcing, in the unit of the record. A message
names a gridded forcing, never recharge alone, since every variable reads it.
"""

from __future__ import annotations

import warnings
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.spatial.forcing.cells import discretize_fields_on_cells, spatial_mean_from_fields
from hydromodpy.spatial.forcing.rasters import discretize_from_xarray
from tests._helpers.forcing_cases import (
    MM_DAY_TO_M_S,
    PIXEL,
    centres,
    daily_field,
    field_record,
    grid_dataset,
    pixel_axes,
    polygon_mesh,
    static_field,
    window,
    write_geotiff,
)

pytestmark = pytest.mark.fast

NODATA = -9999.0
METHODS = ("nearest", "linear", "idw", "area")
UNDER_A_CELL = (2, 1)
"""Row and column of a pixel that sits under the centre of cell 4."""
BEYOND_THE_CELLS = (0, 3)
"""Row and column of the north-east pixel, which no cell reaches."""
_ACCEPTED = r"\(\.nc, \.nc4, \.netcdf, \.tif, \.tiff\)"


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


def _bands(rates: list[float], nrow: int = 3, ncol: int = 4) -> np.ndarray:
    return np.asarray(rates, dtype=float)[:, None, None] * np.ones((len(rates), nrow, ncol))


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

    assert [_rate(result[k]) for k in range(3)] == pytest.approx([5.2, 7.0, 7.0])


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


@pytest.mark.parametrize(
    ("data", "type_name"),
    [(np.ones((2, 2)), "ndarray"), (xr.DataArray(np.ones((2, 2))), "DataArray")],
    ids=["array", "data-array"],
)
def test_a_record_of_an_unknown_type_is_refused(data, type_name):
    match = (
        rf"holds a {type_name}\. The forcing reads an xarray Dataset or the path of a "
        rf"NetCDF or GeoTIFF file {_ACCEPTED}"
    )
    with pytest.raises(DataContractViolation, match=match):
        _on_cells(field_record(data), 2, 2, nper=1)


@pytest.mark.parametrize("as_text", [False, True], ids=["path", "text"])
def test_a_file_of_an_unknown_suffix_is_refused(tmp_path: Path, as_text):
    path = tmp_path / "recharge.ASC"
    path.write_text("ncols 2\n", encoding="utf-8")
    match = (
        rf"recharge\.ASC has the suffix '\.asc'\. The forcing reads NetCDF or GeoTIFF files "
        rf"{_ACCEPTED}"
    )
    with pytest.raises(DataContractViolation, match=match):
        _on_cells(field_record(str(path) if as_text else path), 2, 2, nper=1)


def test_a_grid_clipped_to_no_pixel_is_refused():
    record = field_record(grid_dataset(np.ones((2, 0)), np.zeros(0), pixel_axes(2, 2)[1]))

    with pytest.raises(ValueError, match=r"^gridded forcing values cannot be empty"):
        _on_cells(record, 2, 2, nper=1)


def test_a_single_band_geotiff_gives_its_rate_to_every_period(tmp_path: Path):
    x, y = pixel_axes(4, 5)
    path = write_geotiff(tmp_path / "recharge.tif", np.full((1, 4, 5), 8.0), x, y, "float32")

    result = _on_cells(field_record(path), 4, 5, nper=2)

    assert sorted(result) == [0, 1]
    for kper in range(2):
        assert result[kper].shape == (20,)
        assert _rate(result[kper]) == pytest.approx(8.0, rel=1e-4)


@pytest.mark.parametrize("days", [None, 31], ids=["static", "daily"])
def test_a_netcdf_gives_the_mean_rate_of_its_days(tmp_path: Path, days):
    path = tmp_path / "recharge.nc"
    times = None if days is None else pd.date_range("2020-01-01", periods=days, freq="D")
    values = np.full((3, 4) if days is None else (days, 3, 4), 6.0)
    grid_dataset(values, *pixel_axes(3, 4), times).to_netcdf(path)
    january = None if days is None else window("2020-01-01", "2020-01-31")

    result = _on_cells(field_record(path, days=days), 3, 4, nper=1, simulation_window=january)

    assert result[0].shape == (12,)
    assert _rate(result[0]) == pytest.approx(6.0, rel=1e-4)


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
        (
            "error",
            pytest.raises(ValueError, match="no GeoTIFF forcing band mapped to stress period 2"),
        ),
    ],
    ids=["ignore", "warn", "error"],
)
def test_a_period_no_band_reaches_takes_the_last_band_or_stops_the_run(
    tmp_path: Path, policy, expectation
):
    path = write_geotiff(tmp_path / "recharge.tif", _bands([2.0, 4.0]), *pixel_axes(3, 4))
    three_months = window("2020-01-01", "2020-03-31", coverage_policy=policy)

    with expectation, warnings.catch_warnings():
        if policy == "ignore":
            warnings.simplefilter("error", UserWarning)
        result = _on_cells(field_record(path), 3, 4, nper=3, simulation_window=three_months)
        assert [_rate(result[k]) for k in range(3)] == pytest.approx([2.0, 4.0, 4.0])


# ---- a nodata pixel ------------------------------------------------------


def _raster(nodata_at: tuple[int, int] | None, bands: int = 1) -> np.ndarray:
    values = np.full((bands, 4, 4), 5.0)
    if nodata_at is not None:
        values[(-1, *nodata_at)] = NODATA
    return values


def _cells_mesh():
    """The 3 x 3 square cells of ``centres`` as polygons, row 0 at the north."""
    return polygon_mesh(
        [
            np.array([[0, 0], [1, 0], [1, 1], [0, 1]]) * PIXEL + [col * PIXEL, (2 - row) * PIXEL]
            for row in range(3)
            for col in range(3)
        ]
    )


def _on_nine_cells(data, method: str, nper: int = 1, simulation_window=None, days=None):
    return discretize_fields_on_cells(
        load_result=LoadResult(fields=[field_record(data, days=days)]),
        centers=centres(3, 3),
        nper=nper,
        simulation_window=simulation_window,
        method=method,
        mesh=_cells_mesh(),
    )


def _geotiff(tmp_path: Path, values: np.ndarray) -> Path:
    import rasterio

    path = write_geotiff(tmp_path / "recharge.tif", values, *pixel_axes(4, 4))
    with rasterio.open(path, "r+") as dst:
        dst.nodata = NODATA
    return path


def _netcdf(tmp_path: Path, values: np.ndarray) -> Path:
    path = tmp_path / "recharge.nc"
    data = np.where(values[0] == NODATA, np.nan, values[0])
    grid_dataset(data, *pixel_axes(4, 4)).to_netcdf(
        path, encoding={"recharge": {"_FillValue": NODATA}}
    )
    return path


WRITERS = {"geotiff": _geotiff, "netcdf": _netcdf}


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("method", METHODS)
def test_a_cell_on_a_nodata_pixel_is_refused(tmp_path: Path, writer: str, method: str):
    path = WRITERS[writer](tmp_path, _raster(UNDER_A_CELL))

    with pytest.raises(DataContractViolation, match=r"nodata pixel under 1 cell\(s\).*cell 4\."):
        _on_nine_cells(path, method)


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("method", ("nearest", "linear", "area"))
def test_a_nodata_pixel_no_cell_reads_is_accepted(tmp_path: Path, writer: str, method: str):
    path = WRITERS[writer](tmp_path, _raster(BEYOND_THE_CELLS))

    result = _on_nine_cells(path, method)

    np.testing.assert_allclose(result[0], 5.0 * MM_DAY_TO_M_S, rtol=1e-12)


def test_an_idw_cell_refuses_a_nodata_pixel_among_its_neighbours(tmp_path: Path):
    path = _geotiff(tmp_path, _raster(BEYOND_THE_CELLS))
    off_the_pixels = centres(3, 3) + 1.0

    def on_cells(method: str) -> dict[int, np.ndarray]:
        return discretize_fields_on_cells(
            load_result=LoadResult(fields=[field_record(path)]),
            centers=off_the_pixels,
            nper=1,
            method=method,
        )

    np.testing.assert_allclose(on_cells("nearest")[0], 5.0 * MM_DAY_TO_M_S, rtol=1e-12)
    with pytest.raises(DataContractViolation, match=r"nodata pixel under 9 cell\(s\)"):
        on_cells("idw")


def test_a_nodata_pixel_of_a_later_band_names_its_band(tmp_path: Path):
    values = _raster(None, bands=2)
    values[(1, *UNDER_A_CELL)] = NODATA
    path = _geotiff(tmp_path, values)

    with pytest.raises(DataContractViolation, match=r"recharge\.tif .* in band 2, first cell 4"):
        _on_nine_cells(path, "nearest", nper=2)


@pytest.mark.parametrize("method", METHODS)
def test_a_band_of_nodata_only_is_refused(tmp_path: Path, method: str):
    path = _geotiff(tmp_path, np.full((1, 4, 4), NODATA))

    with pytest.raises(
        DataContractViolation, match=r"recharge\.tif holds no valid pixel in band 1"
    ):
        _on_nine_cells(path, method)


@pytest.mark.parametrize(
    "simulation_window", [window("2020-01-01", "2020-01-31"), None], ids=["window", "no-window"]
)
def test_a_period_with_one_nodata_day_is_nodata_for_the_whole_period(simulation_window):
    days = np.full((3, 4, 4), 5.0)
    days[(0, *UNDER_A_CELL)] = np.nan
    data = grid_dataset(days, *pixel_axes(4, 4), pd.date_range("2020-01-01", periods=3, freq="D"))

    with pytest.raises(DataContractViolation, match=r"dataset .* in stress period 0, first cell 4"):
        _on_nine_cells(data, "nearest", simulation_window=simulation_window, days=3)


# ---- the spatial mean ----------------------------------------------------


def _mean(*records) -> pd.Series | None:
    return spatial_mean_from_fields(LoadResult(fields=list(records)))


def _ramp(nrow: int = 2, ncol: int = 3) -> np.ndarray:
    """A grid whose pixels hold 0 to 5 mm/day, mean 2.5."""
    return np.arange(nrow * ncol, dtype=float).reshape(nrow, ncol)


def _nodata_grid() -> np.ndarray:
    values = _ramp()
    values[0, 1] = np.nan
    return values


def test_a_static_grid_has_one_mean_value_and_a_daily_grid_one_a_day():
    static = _mean(static_field(3, 4, 7.5))
    daily = _mean(daily_field(2, 3, [1.0, 2.0, 3.0]))

    assert len(static) == 1
    assert static.iloc[0] == pytest.approx(7.5, rel=1e-10)
    assert list(daily.index) == list(pd.date_range("2020-01-01", periods=3, freq="D"))
    np.testing.assert_allclose(daily.to_numpy(), [1.0, 2.0, 3.0], rtol=1e-10)


def test_two_fields_give_the_mean_of_their_spatial_means_day_by_day():
    series = _mean(daily_field(2, 2, [1.0, 2.0, 3.0]), daily_field(2, 2, [3.0, 4.0, 5.0]))

    np.testing.assert_allclose(series.to_numpy(), [2.0, 3.0, 4.0])


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


@pytest.mark.parametrize(
    "records",
    [
        [],
        [field_record(xr.Dataset())],
        [field_record(np.ones((2, 2)))],
        [field_record(Path("recharge.asc"))],
    ],
    ids=["no-field", "no-variable", "an-array", "an-unknown-suffix"],
)
def test_a_source_with_no_readable_grid_has_no_spatial_mean(records):
    assert _mean(*records) is None


@pytest.mark.parametrize(
    ("record", "match"),
    [
        (
            field_record(grid_dataset(_nodata_grid(), *pixel_axes(2, 3))),
            "^gridded forcing values must contain only finite numeric values",
        ),
        (
            field_record(grid_dataset(np.ones((2, 0)), np.zeros(0), pixel_axes(2, 3)[1])),
            "^gridded forcing values cannot be empty",
        ),
        ("geotiff", "^GeoTIFF forcing values must contain only finite"),
    ],
    ids=["a-nodata-pixel", "clipped-to-nothing", "a-geotiff-nodata-pixel"],
)
def test_a_grid_with_a_nodata_pixel_or_no_pixel_has_no_mean(tmp_path: Path, record, match):
    if record == "geotiff":
        path = write_geotiff(tmp_path / "recharge.tif", _nodata_grid()[None], *pixel_axes(2, 3))
        record = field_record(path)
    with pytest.raises(ValueError, match=match):
        _mean(record)
