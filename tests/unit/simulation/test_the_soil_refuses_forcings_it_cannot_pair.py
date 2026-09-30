"""Every way a precipitation or ETP grid can fail the soil reservoir's contract.

``compute_soil_forcings`` reads the loaded ``[data.precipitation]`` and
``[data.etp]`` on its own (spec section 4.3, guards X1 to X12E, X6): each way
a data manager can hand back something the soil reservoir cannot use raises
the exact class and text of that guard.
"""

from __future__ import annotations

import cftime
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import DataContractViolation, MissingForcingError
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult, PointRecord
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import compute_soil_forcings

_CRS = "EPSG:2154"
_X = np.array([0.0, 100.0])
_Y = np.array([100.0, 0.0])
_DAYS = pd.date_range("2015-01-01", periods=10, freq="D")


def _dataset(variable: str, values: np.ndarray, *, days=_DAYS, x=_X, y=_Y) -> xr.Dataset:
    return xr.Dataset(
        {variable: (("time", "y", "x"), values)}, coords={"time": days, "y": y, "x": x}
    )


def _record(
    variable: str, dataset: xr.Dataset, *, crs=_CRS, days=_DAYS, **overrides
) -> FieldRecord:
    kwargs = {
        "variable": variable,
        "source": "sim2",
        "unit": "mm/day",
        "data": dataset,
        "bbox": (0.0, 0.0, 100.0, 100.0),
        "crs": crs,
        "date_start": days[0],
        "date_end": days[-1],
    }
    kwargs.update(overrides)
    return FieldRecord(**kwargs)


def _valid_precipitation() -> LoadResult:
    values = np.full((len(_DAYS), 2, 2), 5.0)
    return LoadResult(fields=[_record("precipitation", _dataset("precipitation", values))])


def _valid_etp() -> LoadResult:
    values = np.full((len(_DAYS), 2, 2), 2.0)
    return LoadResult(fields=[_record("etp", _dataset("etp", values))])


_WINDOW = ResolvedSimulationTimeWindow(
    start=_DAYS[0], end=_DAYS[-1], step_value=1, step_unit="day", coverage_policy="error"
)
_CONFIG = SoilReservoirConfig(ru=100.0, spinup="none")


def _compute(*, precipitation=None, etp=None, window=_WINDOW, config=_CONFIG):
    return compute_soil_forcings(
        precipitation=_valid_precipitation() if precipitation is None else precipitation,
        etp=_valid_etp() if etp is None else etp,
        config=config,
        window=window,
        model_crs=_CRS,
    )


def test_a_family_that_loaded_nothing_is_missing() -> None:
    with pytest.raises(MissingForcingError) as excinfo:
        _compute(precipitation=LoadResult(), etp=_valid_etp(), window=_WINDOW)
    assert str(excinfo.value) == (
        "[data.precipitation] loaded nothing for 2015-01-01 to 2015-01-10, and the "
        "soil reservoir needs a value for every day: see the error logged above for "
        "the cause, or run hmp data get precipitation on the same extent to test the "
        "source alone."
    )


def test_a_family_with_only_station_points_is_refused() -> None:
    data = pd.DataFrame({"datetime": _DAYS, "value": np.full(len(_DAYS), 5.0)})
    station = PointRecord(
        station_id="X1",
        variable="precipitation",
        source="hubeau",
        unit="mm/day",
        frequency="D",
        data=data,
        date_start=_DAYS[0],
        date_end=_DAYS[-1],
    )
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(points=[station]))
    assert str(excinfo.value) == (
        "[data.precipitation] holds station series, and the soil reservoir reads a "
        'daily grid: use a gridded source such as source = "sim2", or a NetCDF grid '
        'with source = "custom".'
    )


def test_two_grids_in_one_family_are_refused() -> None:
    good = _record("precipitation", _dataset("precipitation", np.full((len(_DAYS), 2, 2), 5.0)))
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[good, good]))
    assert str(excinfo.value) == (
        "[data.precipitation] holds 2 grids, and the soil reservoir reads one: keep "
        "a single [[data.precipitation.sources]] block."
    )


def test_an_unnamed_variable_among_several_is_refused() -> None:
    values = np.full((len(_DAYS), 2, 2), 5.0)
    dataset = xr.Dataset(
        {"foo": (("time", "y", "x"), values), "bar": (("time", "y", "x"), values)},
        coords={"time": _DAYS, "y": _Y, "x": _X},
    )
    record = _record("precipitation", dataset)
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[record]))
    assert str(excinfo.value) == (
        "[data.precipitation] file holds no variable named 'precipitation' (it "
        "holds ['foo', 'bar']): name the grid 'precipitation'."
    )


def test_the_wrong_dimensions_are_refused() -> None:
    values = np.full((len(_DAYS), 2, 2), 5.0)
    dataset = xr.Dataset(
        {"precipitation": (("time", "lat", "lon"), values)},
        coords={"time": _DAYS, "lat": _Y, "lon": _X},
    )
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[_record("precipitation", dataset)]))
    assert "grid has dimensions" in str(excinfo.value)
    assert "rename the dimensions of the file" in str(excinfo.value)


def test_a_non_standard_calendar_is_refused() -> None:
    times = cftime.num2date(
        np.arange(len(_DAYS)), units="days since 2015-01-01", calendar="360_day"
    )
    values = np.full((len(_DAYS), 2, 2), 5.0)
    dataset = xr.Dataset(
        {"precipitation": (("time", "y", "x"), values)},
        coords={"time": times, "y": _Y, "x": _X},
    )
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[_record("precipitation", dataset)]))
    assert str(excinfo.value) == (
        "[data.precipitation] uses the '360_day' calendar, and the soil reservoir "
        "needs real dates: convert the file to the standard calendar first."
    )


def test_a_grid_in_another_crs_than_the_model_is_refused() -> None:
    record = _record(
        "precipitation",
        _dataset("precipitation", np.full((len(_DAYS), 2, 2), 5.0)),
        crs="EPSG:4326",
    )
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[record]))
    assert str(excinfo.value) == (
        "[data.precipitation] is in EPSG:4326 and the model in EPSG:2154: forcing "
        "grids are never reprojected, so the soil columns would land on the wrong "
        "cells. Reproject the file to EPSG:2154, or set [geographic] crs_project = "
        '"EPSG:4326".'
    )


def test_an_irregular_time_step_is_refused() -> None:
    days = pd.DatetimeIndex(list(_DAYS[:5]) + [_DAYS[4] + pd.Timedelta(days=3)] + list(_DAYS[5:9]))
    values = np.full((len(days), 2, 2), 5.0)
    dataset = _dataset("precipitation", values, days=days)
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[_record("precipitation", dataset, days=days)]))
    assert "holds one value every" in str(excinfo.value)
    assert "give it daily values" in str(excinfo.value)


def test_a_grid_shorter_than_the_window_is_refused() -> None:
    short_days = _DAYS[:5]
    values = np.full((len(short_days), 2, 2), 5.0)
    dataset = _dataset("precipitation", values, days=short_days)
    record = _record("precipitation", dataset, days=short_days)
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[record]))
    assert str(excinfo.value) == (
        "[data.precipitation] covers 2015-01-01 to 2015-01-05, and the run needs "
        "every day from 2015-01-01 to 2015-01-10: extend the source period, or "
        "narrow [simulation.time]."
    )


def test_a_missing_value_is_refused() -> None:
    values = np.full((len(_DAYS), 2, 2), 5.0)
    values[3, 1, 0] = np.nan
    record = _record("precipitation", _dataset("precipitation", values))
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[record]))
    assert str(excinfo.value) == (
        "[data.precipitation] has 1 missing values between 2015-01-01 and "
        "2015-01-10, the first on 2015-01-04 in the cell at x = 0, y = 0: the soil "
        "reservoir needs a value for every day and cell. Fill the gaps, or narrow "
        "[simulation.time] to the covered days."
    )


def test_a_negative_value_is_refused() -> None:
    values = np.full((len(_DAYS), 2, 2), 5.0)
    values[2, 0, 1] = -1.5
    record = _record("precipitation", _dataset("precipitation", values))
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[record]))
    assert str(excinfo.value) == (
        "[data.precipitation] has 1 negative values, the first -1.5 mm/day on "
        "2015-01-03: precipitation cannot be negative. Check the file and its unit."
    )


def test_a_negative_etp_value_names_etp() -> None:
    values = np.full((len(_DAYS), 2, 2), 2.0)
    values[0, 0, 0] = -0.5
    record = _record("etp", _dataset("etp", values))
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(etp=LoadResult(fields=[record]))
    assert "etp cannot be negative" in str(excinfo.value)


def test_a_full_year_of_near_zero_precipitation_is_refused() -> None:
    days = pd.date_range("2015-01-01", periods=365, freq="D")
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    precip_values = np.full((len(days), 2, 2), 0.05)
    etp_values = np.full((len(days), 2, 2), 2.0)
    precipitation = LoadResult(
        fields=[
            _record("precipitation", _dataset("precipitation", precip_values, days=days), days=days)
        ]
    )
    etp = LoadResult(fields=[_record("etp", _dataset("etp", etp_values, days=days), days=days)])
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=precipitation, etp=etp, window=window)
    assert "never exceeds 0.05 mm/day over 365 days" in str(excinfo.value)


def test_an_excessive_precipitation_value_is_refused() -> None:
    values = np.full((len(_DAYS), 2, 2), 5.0)
    values[1, 0, 0] = 1500.0
    record = _record("precipitation", _dataset("precipitation", values))
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(precipitation=LoadResult(fields=[record]))
    assert str(excinfo.value) == (
        "[data.precipitation] reaches 1500 mm/day on 2015-01-02, beyond any daily "
        "rainfall: check the unit of the file and convert it to mm/day."
    )


def test_an_excessive_etp_value_is_refused() -> None:
    values = np.full((len(_DAYS), 2, 2), 2.0)
    values[1, 0, 0] = 45.0
    record = _record("etp", _dataset("etp", values))
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(etp=LoadResult(fields=[record]))
    assert str(excinfo.value) == (
        "[data.etp] reaches 45 mm/day on 2015-01-02, beyond any reference "
        "evapotranspiration: check the unit of the file and convert it to mm/day."
    )


def test_precipitation_and_etp_on_different_grids_are_refused() -> None:
    etp_values = np.full((len(_DAYS), 2, 2), 2.0)
    other_x = np.array([0.0, 50.0])
    etp_record = _record("etp", _dataset("etp", etp_values, x=other_x))
    with pytest.raises(DataContractViolation) as excinfo:
        _compute(etp=LoadResult(fields=[etp_record]))
    assert str(excinfo.value) == (
        "[data.precipitation] and [data.etp] come on two grids (4 and 4 cells, or "
        "as many cells at other places): the soil reservoir pairs them cell by "
        "cell. Load both from the same provider, or regrid one file onto the other."
    )
