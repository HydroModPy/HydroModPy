"""Station series on the cells of a mesh, :mod:`hydromodpy.spatial.forcing.stations`."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.spatial.forcing.cells import discretize_points_on_cells
from tests._helpers.forcing_cases import MM_DAY_TO_M_S, centres, station, window

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
    unlocated = replace(station("nocoord", 0.0, 0.0, 5.0, days=5), location=None)

    result = discretize_points_on_cells(
        load_result=LoadResult(points=[unlocated]), centers=centres(2, 2), nper=1
    )

    assert np.all(result[0] == 0.0)


@pytest.mark.parametrize(
    ("values", "simulation_window", "expected"),
    [
        (
            [10.0] * 31 + [20.0] * 29,
            window("2020-01-01", "2020-02-29", coverage_policy="error"),
            [10.0, 20.0],
        ),
        ([float(day + 1) for day in range(31)], None, [16.0, 16.0]),
    ],
    ids=["its-mean-in-each-period", "without-a-window-its-whole-mean"],
)
def test_a_station_gives_each_period_its_mean(values, simulation_window, expected):
    result = discretize_points_on_cells(
        load_result=LoadResult(points=[station("S1", 5.0, 5.0, values)]),
        centers=centres(2, 2),
        nper=2,
        simulation_window=simulation_window,
    )

    for kper, rate in enumerate(expected):
        np.testing.assert_allclose(result[kper], rate * MM_DAY_TO_M_S)


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
