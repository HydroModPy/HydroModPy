"""Station series on the cells of a mesh, :mod:`hydromodpy.spatial.mesh.forcing._points`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.spatial.mesh.forcing import discretize_points_on_cells
from tests.unit.mesh.forcing.forcing_cases import MM_DAY_TO_M_S, centres, station, window

pytestmark = pytest.mark.fast


def test_one_station_gives_its_rate_to_every_cell():
    result = discretize_points_on_cells(
        load_result=LoadResult(points=[station("S1", 25.0, 15.0, 8.0)]),
        centers=centres(3, 4),
        nper=1,
        method="nearest",
    )

    assert result[0].shape == (12,)
    np.testing.assert_allclose(result[0], 8.0 * MM_DAY_TO_M_S, rtol=1e-6)


def test_a_station_without_location_is_left_out():
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    unlocated = PointRecord(
        station_id="nocoord",
        variable="recharge",
        source="test",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": 5.0}),
        date_start=dates[0].to_pydatetime(),
        date_end=dates[-1].to_pydatetime(),
        location=None,
    )

    result = discretize_points_on_cells(
        load_result=LoadResult(points=[unlocated]), centers=centres(2, 2), nper=1
    )

    assert np.all(result[0] == 0.0)


def test_a_station_takes_its_mean_in_each_period():
    rising = station("S1", 5.0, 5.0, [10.0] * 31 + [20.0] * 29)

    result = discretize_points_on_cells(
        load_result=LoadResult(points=[rising]),
        centers=centres(2, 2),
        nper=2,
        simulation_window=window("2020-01-01", "2020-02-29", coverage_policy="error"),
    )

    np.testing.assert_allclose(result[0], 10.0 * MM_DAY_TO_M_S)
    np.testing.assert_allclose(result[1], 20.0 * MM_DAY_TO_M_S)


def test_without_a_window_a_station_gives_its_whole_mean_to_every_period():
    rising = station("S1", 5.0, 5.0, [float(day + 1) for day in range(31)])

    result = discretize_points_on_cells(
        load_result=LoadResult(points=[rising]), centers=centres(2, 2), nper=2
    )

    for kper in range(2):
        np.testing.assert_allclose(result[kper], 16.0 * MM_DAY_TO_M_S)


def test_each_station_reads_its_own_unit():
    west = station("W", 5.0, 5.0, 10.0, unit="mm/day")
    east = station("E", 35.0, 5.0, 0.02, unit="m/day")

    result = discretize_points_on_cells(
        load_result=LoadResult(points=[west, east]),
        centers=centres(1, 4),
        nper=1,
        source_unit="m/s",
    )

    np.testing.assert_allclose(result[0], np.array([10.0, 10.0, 20.0, 20.0]) * MM_DAY_TO_M_S)


@pytest.mark.parametrize(
    ("simulation_window", "match"),
    [
        (
            window("2020-01-01", "2020-01-31"),
            r"The point forcing record of station S1 contains non-finite values",
        ),
        (None, r"point forcing contains non-finite values"),
    ],
    ids=["with-window", "without-window"],
)
def test_a_station_with_a_missing_value_is_refused(simulation_window, match):
    gap = station("S1", 5.0, 5.0, [2.0, np.nan, 2.0])

    with pytest.raises(ValueError, match=match):
        discretize_points_on_cells(
            load_result=LoadResult(points=[gap]),
            centers=centres(2, 2),
            nper=1,
            simulation_window=simulation_window,
        )
