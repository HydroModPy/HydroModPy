"""A gridded forcing read from a dataset, a NetCDF or a GeoTIFF, :mod:`~.forcing.rasters`.

A message names a gridded forcing, never recharge alone, since every variable reads it.
"""

from __future__ import annotations

import warnings
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pyproj import CRS

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.forcing.cells import discretize_fields_on_cells, spatial_mean_from_fields
from hydromodpy.spatial.forcing.rasters import discretize_from_xarray
from hydromodpy.spatial.forcing.sources import ForcingGridError
from tests._helpers import forcing_cases as fc
from tests._helpers import geotiffs

pytestmark = pytest.mark.fast

NODATA = -9999.0
METHODS = ("nearest", "linear", "idw", "area")
UNDER_A_CELL = (2, 1)  # the pixel under the centre of cell 4
BEYOND_THE_CELLS = (0, 3)  # the north-east pixel, which no cell reaches
_ACCEPTED = r"\(\.nc, \.nc4, \.netcdf, \.tif, \.tiff\)"
_DAYS = [float(day + 1) for day in range(31)]


def _rate(array: np.ndarray) -> float:
    """The uniform rate of *array*, in mm/day."""
    assert np.ptp(array) == pytest.approx(0.0, abs=1e-15)
    return float(array[0]) / fc.MM_DAY_TO_M_S


def _bands(rates: list[float], nrow: int = 3, ncol: int = 4) -> np.ndarray:
    return np.asarray(rates, dtype=float)[:, None, None] * np.ones((len(rates), nrow, ncol))


def _geotiff(rates: list[float], nrow: int = 3, ncol: int = 4, dtype: str = "float32"):
    def build(folder: Path):
        bands = _bands(rates, nrow, ncol)
        path = fc.write_geotiff(folder / "recharge.tif", bands, *fc.pixel_axes(nrow, ncol), dtype)
        return fc.field_record(path)

    return build


def _netcdf(days: int | None):
    def build(folder: Path):
        times = None if days is None else pd.date_range("2020-01-01", periods=days, freq="D")
        values = np.full((3, 4) if days is None else (days, 3, 4), 6.0)
        fc.grid_dataset(values, *fc.pixel_axes(3, 4), times).to_netcdf(folder / "recharge.nc")
        return fc.field_record(folder / "recharge.nc", days=days)

    return build


@pytest.mark.parametrize(
    ("build", "shape", "simulation_window", "rates"),
    [
        (lambda _: fc.static_field(4, 5, 5.0), (4, 5), None, [5.0, 5.0, 5.0]),
        (lambda _: fc.daily_field(2, 3, _DAYS), (2, 3), fc.window("2020-01-01", "2020-01-31"), [16.0]),
        (lambda _: fc.daily_field(2, 3, [10.0] * 31 + [20.0] * 29), (2, 3), fc.window("2020-01-01", "2020-02-29"), [10.0, 20.0]),
        (lambda _: fc.daily_field(2, 2, [5.0] * 9 + [7.0]), (2, 2), fc.window("2020-01-01", "2020-03-31"), [5.2, 7.0, 7.0]),
        # Daily slices on 6-hour periods: 18:00 is nearer to the next day's slice,
        # but the slice in force is the one of its own day.
        (lambda _: fc.daily_field(1, 1, [1.0, 3.0]), (1, 1),
         fc.window("2020-01-01", "2020-01-02 23:00", 6, "hour", coverage_policy="error"), [1.0] * 4 + [3.0] * 4),
        (lambda _: fc.daily_field(2, 2, [1.0, 3.0, 5.0]), (2, 2), None, [1.0, 3.0, 5.0]),
        (_geotiff([8.0], 4, 5), (4, 5), None, [8.0, 8.0]),
        (_netcdf(None), (3, 4), None, [6.0]),
        (_netcdf(31), (3, 4), fc.window("2020-01-01", "2020-01-31"), [6.0]),
        (_geotiff([2.0, 4.0, 6.0]), (3, 4), None, [2.0, 4.0, 6.0]),
        (_geotiff([2.0, 4.0, 6.0, 8.0], dtype="float64"), (3, 4), fc.window("2020-01-01", "2020-02-29"), [3.0, 7.0]),
    ],
    ids=["static-grid-every-period", "daily-mean-of-january", "daily-january-then-february",
         "after-the-last-slice-under-ignore", "gap-takes-the-slice-in-force", "one-slice-a-period-without-window",
         "single-band-geotiff", "static-netcdf", "daily-netcdf", "one-band-a-period-without-window",
         "bands-shared-among-periods"],
)  # fmt: skip
def test_each_period_takes_the_mean_of_its_slices(tmp_path, build, shape, simulation_window, rates):
    result = fc.fields_on_cells([build(tmp_path)], *shape, len(rates), simulation_window=simulation_window)  # fmt: skip
    assert sorted(result) == list(range(len(rates)))
    assert {result[kper].shape for kper in result} == {(shape[0] * shape[1],)}
    assert [_rate(result[kper]) for kper in result] == pytest.approx(rates, rel=1e-10)


def test_a_grid_with_an_empty_time_axis_and_no_window_gives_no_period():
    times = pd.DatetimeIndex([], dtype="datetime64[ns]")
    dataset = fc.grid_dataset(np.zeros((0, 2, 2)), *fc.pixel_axes(2, 2), times)
    assert discretize_from_xarray(dataset, centers=fc.centres(2, 2), nper=2, period_bounds=None, unit_factor=1.0) == {}  # fmt: skip


def test_a_dataset_without_a_data_variable_gives_zero_on_every_period():
    result = fc.fields_on_cells([fc.field_record(xr.Dataset())], nper=2)
    assert sorted(result) == [0, 1]
    assert all(np.all(result[kper] == 0.0) for kper in range(2))


def _asc(folder: Path, as_text: bool) -> Path | str:
    (folder / "recharge.ASC").write_text("ncols 2\n", encoding="utf-8")
    return str(folder / "recharge.ASC") if as_text else folder / "recharge.ASC"


_NO_AXES = r"^The gridded forcing dataset has the variable 'recharge' on the dimensions \('time', 'station'\), among"


def _station_axis_dataset() -> xr.Dataset:
    return xr.Dataset({"recharge": (("time", "station"), np.ones((2, 3)))})


_TYPE = r"holds a {}\. The forcing reads an xarray Dataset or the path of a NetCDF or GeoTIFF file "
_SUFFIX = r"recharge\.ASC has the suffix '\.asc'\. The forcing reads NetCDF or GeoTIFF files "


@pytest.mark.parametrize(
    ("data", "error", "match"),
    [
        (lambda _: np.ones((2, 2)), DataContractViolation, _TYPE.format("ndarray") + _ACCEPTED),
        (lambda _: xr.DataArray(np.ones((2, 2))), DataContractViolation, _TYPE.format("DataArray") + _ACCEPTED),
        (lambda folder: _asc(folder, False), DataContractViolation, _SUFFIX + _ACCEPTED),
        (lambda folder: _asc(folder, True), DataContractViolation, _SUFFIX + _ACCEPTED),
        (lambda _: fc.grid_dataset(np.ones((2, 0)), np.zeros(0), fc.pixel_axes(2, 2)[1]), ForcingGridError,
         r"^The gridded forcing dataset holds no pixel in the static field: its values have the shape \(2, 0\)"),
        (lambda _: _station_axis_dataset(), ForcingGridError, _NO_AXES),
    ],
    ids=["array", "data-array", "unknown-suffix-path", "unknown-suffix-text", "clipped-to-no-pixel",
         "no-x-and-y-axis"],
)  # fmt: skip
def test_a_record_the_forcing_cannot_read_is_refused(tmp_path: Path, data, error, match):
    with pytest.raises(error, match=match):
        fc.fields_on_cells([fc.field_record(data(tmp_path))])


_NO_BAND = "^Coverage check failed for etp: no GeoTIFF forcing band mapped to stress period 2"


@pytest.mark.parametrize(
    ("policy", "expectation"),
    [
        ("ignore", nullcontext()),
        ("warn", pytest.warns(UserWarning, match=_NO_BAND)),
        ("error", pytest.raises(ValueError, match=_NO_BAND)),
    ],
    ids=["ignore", "warn", "error"],
)  # fmt: skip
def test_a_period_no_band_reaches_takes_the_last_band_or_stops_the_run(tmp_path, policy, expectation):  # fmt: skip
    record = replace(_geotiff([2.0, 4.0], dtype="float64")(tmp_path), variable="etp")
    three_months = fc.window("2020-01-01", "2020-03-31", coverage_policy=policy)

    with expectation, warnings.catch_warnings():
        if policy == "ignore":
            warnings.simplefilter("error", UserWarning)
        result = fc.fields_on_cells([record], 3, 4, nper=3, simulation_window=three_months)
        assert [_rate(result[k]) for k in range(3)] == pytest.approx([2.0, 4.0, 4.0])


def _rotated_geotiff(folder: Path) -> FieldRecord:
    import rasterio
    from affine import Affine

    record = _geotiff([5.0], 2, 2)(folder)
    with rasterio.open(record.data, "r+") as dst:
        dst.transform = dst.transform @ Affine.rotation(30.0)
    return record


_UNREAD = r"^The gridded forcing {} holds 3 {} for 2 stress period\(s\){}"
_LINE = r"^The gridded forcing {} is a grid of {} row\(s\) and {} column\(s\)\. interpolation_method 'linear'"


@pytest.mark.parametrize(
    ("build", "nper", "simulation_window", "method", "match"),
    [
        (_geotiff([1.0, 2.0, 3.0]), 2, fc.window("2020-01-01", "2020-02-29"), "nearest",
         _UNREAD.format(r"recharge\.tif", "bands", r"\. Each period takes the same number of bands, so the last 1")),
        (_geotiff([1.0, 2.0, 3.0]), 2, None, "nearest", _UNREAD.format(r"recharge\.tif", "bands", " and no simulation window")),
        (lambda _: fc.daily_field(2, 2, [1.0, 2.0, 3.0]), 2, None, "nearest",
         _UNREAD.format("dataset", "time steps", " and no simulation window, so each of its time steps is one period")),
        (lambda _: fc.static_field(1, 4, 5.0), 1, None, "linear", _LINE.format("dataset", 1, 4)),
        (lambda folder: fc.field_record(geotiffs.write_geotiff(folder / "r.tif", np.full((4, 1), 5.0), cell=fc.PIXEL)),
         1, None, "linear", _LINE.format(r"r\.tif", 4, 1)),
        (_rotated_geotiff, 1, None, "nearest", r"^The GeoTIFF forcing recharge\.tif has a rotated transform"),
    ],
    ids=["bands-not-a-multiple-of-the-periods", "more-bands-than-periods-without-window",
         "more-time-steps-than-periods-without-window", "linear-on-one-row", "linear-on-one-column",
         "rotated-geotiff"],
)  # fmt: skip
def test_a_grid_the_periods_or_the_cells_cannot_read_whole_is_refused(tmp_path, build, nper, simulation_window, method, match):  # fmt: skip
    with pytest.raises(DataContractViolation, match=match):
        fc.fields_on_cells([build(tmp_path)], 2, 2, nper, simulation_window=simulation_window, method=method)  # fmt: skip


# ---- the CRS of the grid against the CRS of the mesh ---------------------

_L93_WKT = CRS.from_epsg(2154).to_wkt()
_LOCAL_FRAME = 'LOCAL_CS["array grid",LOCAL_DATUM["local origin",0],UNIT["metre",1]]'
_OTHER_CRS = r"^The recharge grid {} is in {} and the mesh in EPSG:2154\. A forcing grid is never reprojected"


@pytest.mark.parametrize(
    ("build", "grid_crs", "mesh_crs", "match"),
    [
        (lambda _: fc.static_field(2, 2, 5.0), "EPSG:4326", _L93_WKT, _OTHER_CRS.format("dataset", "EPSG:4326")),
        (_geotiff([5.0], 2, 2), "EPSG:32630", "EPSG:2154", _OTHER_CRS.format(r"recharge\.tif", "EPSG:32630")),
        (lambda _: fc.static_field(2, 2, 5.0), "EPSG:2154", _L93_WKT, None),
        (lambda _: fc.static_field(2, 2, 5.0), fc.L93_PROJ4_WITHOUT_DATUM, _L93_WKT, None),
        (lambda _: fc.static_field(2, 2, 5.0), "", _L93_WKT, None),
        (lambda _: fc.static_field(2, 2, 5.0), "not-a-crs", _L93_WKT, None),
        (lambda _: fc.static_field(2, 2, 5.0), "EPSG:4326", None, None),
        (lambda _: fc.static_field(2, 2, 5.0), "EPSG:4326", _LOCAL_FRAME, None),
    ],
    ids=["dataset-in-another-crs", "geotiff-record-in-another-crs", "same-crs-written-otherwise",
         "proj4-without-datum-identified-as-the-mesh-crs",
         "grid-without-crs-is-not-compared", "unreadable-grid-crs-is-not-compared",
         "mesh-without-crs-is-not-compared", "mesh-in-a-local-frame-is-not-compared"],
)  # fmt: skip
def test_a_grid_in_another_crs_than_the_mesh_is_refused(tmp_path, build, grid_crs, mesh_crs, match):  # fmt: skip
    record = replace(build(tmp_path), crs=grid_crs)
    refused = pytest.raises(DataContractViolation, match=match) if match else nullcontext()
    with refused:
        assert _rate(fc.fields_on_cells([record], mesh_crs=mesh_crs)[0]) == pytest.approx(5.0)


# ---- a nodata pixel ------------------------------------------------------


def _raster(nodata_at: tuple[int, int] | None, bands: int = 1) -> np.ndarray:
    values = np.full((bands, 4, 4), 5.0)
    if nodata_at is not None:
        values[(-1, *nodata_at)] = NODATA
    return values


def _on_nine_cells(data, method: str, nper: int = 1, simulation_window=None, days=None):
    """Read *data* on the 3 x 3 square cells of ``centres``, given as polygons too."""
    rings = [
        np.array([[0, 0], [1, 0], [1, 1], [0, 1]]) * fc.PIXEL
        + [col * fc.PIXEL, (2 - row) * fc.PIXEL]
        for row in range(3)
        for col in range(3)
    ]
    return discretize_fields_on_cells(
        load_result=LoadResult(fields=[fc.field_record(data, days=days)]),
        centers=fc.centres(3, 3),
        nper=nper,
        simulation_window=simulation_window,
        method=method,
        mesh=fc.polygon_mesh(rings),
        mesh_crs=None,
    )


def _nodata_geotiff(tmp_path: Path, values: np.ndarray) -> Path:
    import rasterio

    path = fc.write_geotiff(tmp_path / "recharge.tif", values, *fc.pixel_axes(4, 4))
    with rasterio.open(path, "r+") as dst:
        dst.nodata = NODATA
    return path


def _nodata_netcdf(tmp_path: Path, values: np.ndarray) -> Path:
    data = np.where(values[0] == NODATA, np.nan, values[0])
    encoding = {"recharge": {"_FillValue": NODATA}}
    fc.grid_dataset(data, *fc.pixel_axes(4, 4)).to_netcdf(tmp_path / "recharge.nc", encoding=encoding)  # fmt: skip
    return tmp_path / "recharge.nc"


def _nodata_attribute(key: str):
    def write(_folder: Path, values: np.ndarray) -> xr.Dataset:
        dataset = fc.grid_dataset(values[0], *fc.pixel_axes(4, 4))
        dataset["recharge"].attrs[key] = NODATA
        return dataset

    return write


WRITERS = {
    "geotiff": _nodata_geotiff,
    "netcdf": _nodata_netcdf,
    **{
        f"dataset-{key}": _nodata_attribute(key)
        for key in ("nodata", "_FillValue", "missing_value")
    },
}


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("method", METHODS)
def test_a_nodata_pixel_is_refused_under_a_cell_and_accepted_beyond(tmp_path, writer, method):
    (tmp_path / "beyond").mkdir()
    under = WRITERS[writer](tmp_path, _raster(UNDER_A_CELL))
    with pytest.raises(DataContractViolation, match=r"nodata pixel under 1 cell\(s\).*cell 4\."):
        _on_nine_cells(under, method)
    if method == "idw":  # its neighbours reach the north-east pixel
        return
    beyond = WRITERS[writer](tmp_path / "beyond", _raster(BEYOND_THE_CELLS))
    np.testing.assert_allclose(_on_nine_cells(beyond, method)[0], 5.0 * fc.MM_DAY_TO_M_S, rtol=1e-12)  # fmt: skip


def test_an_idw_cell_refuses_a_nodata_pixel_among_its_neighbours(tmp_path: Path):
    path = _nodata_geotiff(tmp_path, _raster(BEYOND_THE_CELLS))

    def on_cells(method: str) -> dict[int, np.ndarray]:
        return discretize_fields_on_cells(
            load_result=LoadResult(fields=[fc.field_record(path)]),
            centers=fc.centres(3, 3) + 1.0,
            nper=1,
            method=method,
            mesh_crs=None,
        )

    np.testing.assert_allclose(on_cells("nearest")[0], 5.0 * fc.MM_DAY_TO_M_S, rtol=1e-12)
    with pytest.raises(DataContractViolation, match=r"nodata pixel under 9 cell\(s\)"):
        on_cells("idw")


def test_a_nodata_pixel_of_a_later_band_names_its_band(tmp_path: Path):
    values = _raster(None, bands=2)
    values[(1, *UNDER_A_CELL)] = NODATA
    with pytest.raises(DataContractViolation, match=r"recharge\.tif .* in band 2, first cell 4"):
        _on_nine_cells(_nodata_geotiff(tmp_path, values), "nearest", nper=2)


@pytest.mark.parametrize("method", METHODS)
def test_a_band_of_nodata_only_is_refused(tmp_path: Path, method: str):
    path = _nodata_geotiff(tmp_path, np.full((1, 4, 4), NODATA))
    with pytest.raises(DataContractViolation, match=r"recharge\.tif holds no valid pixel in band 1"):  # fmt: skip
        _on_nine_cells(path, method)


@pytest.mark.parametrize(
    ("simulation_window", "nper"), [(fc.window("2020-01-01", "2020-01-31"), 1), (None, 3)], ids=["window", "no-window"]
)  # fmt: skip
def test_a_period_with_one_nodata_day_is_nodata_for_the_whole_period(simulation_window, nper):
    days = np.full((3, 4, 4), 5.0)
    days[(0, *UNDER_A_CELL)] = np.nan
    times = pd.date_range("2020-01-01", periods=3, freq="D")
    data = fc.grid_dataset(days, *fc.pixel_axes(4, 4), times)
    with pytest.raises(DataContractViolation, match=r"dataset .* in stress period 0, first cell 4"):
        _on_nine_cells(data, "nearest", nper, simulation_window=simulation_window, days=3)


# ---- the spatial mean, one value per date in the unit of the record -------


def _mean(*records) -> pd.Series | None:
    return spatial_mean_from_fields(LoadResult(fields=list(records)))


def _ramp(scale: float = 1.0) -> np.ndarray:
    """A 2 x 3 grid whose pixels hold 0 to 5 mm/day times *scale*, mean 2.5 * *scale*."""
    return scale * np.arange(6, dtype=float).reshape(2, 3)


def _nodata_ramp(nodata: float = np.nan, scale: float = 1.0) -> np.ndarray:
    """The ramp with its pixel of value 1 * *scale* set to *nodata*; its valid pixels mean 2.8 * *scale*."""
    values = _ramp(scale)
    values[0, 1] = nodata
    return values


def _ramp_tif(folder: Path, values: np.ndarray, nodata: float | None = None) -> FieldRecord:
    return fc.field_record(geotiffs.write_geotiff(folder / "r.tif", values, cell=fc.PIXEL, nodata=nodata))  # fmt: skip


def _ramp_netcdf(folder: Path, values: np.ndarray) -> FieldRecord:
    encoding = {"recharge": {"_FillValue": NODATA}}
    fc.grid_dataset(values, *fc.pixel_axes(2, 3)).to_netcdf(folder / "recharge.nc", encoding=encoding)  # fmt: skip
    return fc.field_record(folder / "recharge.nc")


def _ramp_dataset(values: np.ndarray, nodata: float | None = None, days: int | None = None, key: str = "nodata") -> FieldRecord:  # fmt: skip
    times = None if days is None else pd.date_range("2020-01-01", periods=days, freq="D")
    dataset = fc.grid_dataset(values, *fc.pixel_axes(2, 3), times)
    if nodata is not None:
        dataset["recharge"].attrs[key] = nodata
    return fc.field_record(dataset, days=days)


def test_a_static_grid_has_one_mean_value_and_a_daily_grid_one_a_day():
    static = _mean(fc.static_field(3, 4, 7.5))
    daily = _mean(fc.daily_field(2, 3, [1.0, 2.0, 3.0]))

    assert len(static) == 1
    assert static.iloc[0] == pytest.approx(7.5, rel=1e-10)
    assert list(daily.index) == list(pd.date_range("2020-01-01", periods=3, freq="D"))
    np.testing.assert_allclose(daily.to_numpy(), [1.0, 2.0, 3.0], rtol=1e-10)
    two = _mean(fc.daily_field(2, 2, [1.0, 2.0, 3.0]), fc.daily_field(2, 2, [3.0, 4.0, 5.0]))
    np.testing.assert_allclose(two.to_numpy(), [2.0, 3.0, 4.0])


def _mean_netcdf(folder: Path, daily: bool) -> pd.Series | None:
    path, axes = folder / "recharge.nc", fc.pixel_axes(2, 3)
    if daily:
        times = pd.date_range("2020-01-01", periods=2, freq="D")
        fc.grid_dataset(np.stack([_ramp(), _ramp(2.0)]), *axes, times).to_netcdf(path)
    else:
        fc.grid_dataset(_ramp(), *axes).to_netcdf(path)
    return _mean(fc.field_record(path, days=2 if daily else None))


@pytest.mark.parametrize(
    ("read", "expected"),
    [
        (lambda folder: _mean_netcdf(folder, daily=False), [2.5]),
        (lambda folder: _mean_netcdf(folder, daily=True), [2.5, 5.0]),
        (lambda folder: _mean(fc.field_record(str(fc.write_geotiff(folder / "r.tif", _ramp()[None], *fc.pixel_axes(2, 3))))), [2.5]),
        (lambda folder: _mean(_ramp_tif(folder, _nodata_ramp(NODATA), nodata=NODATA)), [2.8]),
        (lambda folder: _mean(_ramp_tif(folder, _nodata_ramp())), [2.8]),
        (lambda folder: _mean(_ramp_netcdf(folder, _nodata_ramp())), [2.8]),
        (lambda _: _mean(_ramp_dataset(_nodata_ramp())), [2.8]),
        (lambda _: _mean(_ramp_dataset(_nodata_ramp(NODATA), nodata=NODATA)), [2.8]),
        (lambda _: _mean(_ramp_dataset(_nodata_ramp(NODATA), nodata=NODATA, key="_FillValue")), [2.8]),
        (lambda _: _mean(_ramp_dataset(np.stack([_ramp(), _nodata_ramp(scale=2.0)]), days=2)), [2.5, 5.6]),
    ],
    ids=["static-netcdf", "daily-netcdf", "first-band-of-a-geotiff", "geotiff-declared-nodata-left-out",
         "geotiff-nan-left-out", "netcdf-fill-value-left-out", "dataset-nan-left-out",
         "dataset-nodata-attribute-left-out", "dataset-fill-value-attribute-left-out",
         "daily-dataset-nan-left-out-on-its-day"],
)  # fmt: skip
def test_a_grid_has_the_mean_of_its_valid_pixels(tmp_path: Path, read, expected):
    np.testing.assert_allclose(read(tmp_path).to_numpy(), expected)


@pytest.mark.parametrize(
    "records",
    [[], [fc.field_record(xr.Dataset())], [fc.field_record(np.ones((2, 2)))], [fc.field_record(Path("recharge.asc"))]],
    ids=["no-field", "no-variable", "an-array", "an-unknown-suffix"],
)  # fmt: skip
def test_a_source_with_no_readable_grid_has_no_spatial_mean(records):
    assert _mean(*records) is None


_NO_VALID = (
    r"^The gridded forcing {} holds no valid pixel in {}, on the footprint x 5 to 25 and y 5 to 15 "
)


@pytest.mark.parametrize(
    ("record", "error", "match"),
    [
        (lambda _: fc.field_record(fc.grid_dataset(np.ones((2, 0)), np.zeros(0), fc.pixel_axes(2, 3)[1])),
         ForcingGridError, r"^The gridded forcing dataset holds no pixel in any slice: its values have the shape"),
        (lambda _: fc.field_record(_station_axis_dataset()), ForcingGridError, _NO_AXES),
        (lambda folder: _ramp_tif(folder, np.full((2, 3), NODATA), nodata=NODATA),
         DataContractViolation, _NO_VALID.format(r"r\.tif", "band 1")),
        (lambda folder: _ramp_netcdf(folder, np.full((2, 3), np.nan)),
         DataContractViolation, _NO_VALID.format(r"recharge\.nc", "the static field")),
        (lambda _: _ramp_dataset(np.stack([_ramp(), np.full((2, 3), np.nan)]), days=2),
         DataContractViolation, _NO_VALID.format("dataset", r"time step 1 \(2020-01-02\)")),
    ],
    ids=["clipped-to-nothing", "no-x-and-y-axis", "geotiff-band-of-nodata", "netcdf-of-fill-values", "a-day-of-nan"],
)  # fmt: skip
def test_a_grid_with_no_valid_pixel_has_no_mean(tmp_path: Path, record, error, match):
    with pytest.raises(error, match=match):
        _mean(record(tmp_path))
