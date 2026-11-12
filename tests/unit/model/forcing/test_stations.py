"""Station series on the cells of a mesh, :mod:`hydromodpy.model.forcing.stations`."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from pyproj import CRS

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.model.forcing.stations import period_means
from tests._helpers.forcing_cases import MM_DAY_TO_M_S, points_on_cells, station, window

pytestmark = pytest.mark.fast


def test_one_station_gives_its_rate_to_every_cell_and_one_without_location_none():
    result = points_on_cells([station("S1", 25.0, 15.0, 8.0)], 3, 4, method="nearest")
    unlocated = replace(station("nocoord", 0.0, 0.0, 5.0, days=5), location=None)
    assert result[0].shape == (12,)
    np.testing.assert_allclose(result[0], 8.0 * MM_DAY_TO_M_S, rtol=1e-6)
    assert np.all(points_on_cells([unlocated])[0] == 0.0)


@pytest.mark.parametrize(
    ("values", "simulation_window", "expected"),
    [
        ([10.0] * 31 + [20.0] * 29, window("2020-01-01", "2020-02-29", coverage_policy="error"), [10.0, 20.0]),
        ([float(day + 1) for day in range(31)], None, [16.0, 16.0]),
    ],
    ids=["its-mean-in-each-period", "without-a-window-its-whole-mean"],
)  # fmt: skip
def test_a_station_gives_each_period_its_mean(values, simulation_window, expected):
    stations = [station("S1", 5.0, 5.0, values)]
    result = points_on_cells(stations, nper=2, simulation_window=simulation_window)
    for kper, rate in enumerate(expected):
        np.testing.assert_allclose(result[kper], rate * MM_DAY_TO_M_S)


def test_each_station_reads_its_own_unit():
    west = station("W", 5.0, 5.0, 10.0, unit="mm/day")
    east = station("E", 35.0, 5.0, 0.02, unit="m/day")
    result = points_on_cells([west, east], 1, 4, source_unit="m/s")
    np.testing.assert_allclose(result[0], np.array([10.0, 10.0, 20.0, 20.0]) * MM_DAY_TO_M_S)


@pytest.mark.parametrize(
    ("values", "simulation_window", "match"),
    [
        ([2.0, np.nan, 2.0], window("2020-01-01", "2020-01-31"), r"for etp: The point forcing record of station S1 contains non-finite values"),
        ([2.0, np.nan, 2.0], None, r"for etp: point forcing contains non-finite values"),
        ([], None, r"for etp: stress period 0 contains non-finite values"),
    ],
    ids=["with-window", "without-window", "empty-series-without-window"],
)  # fmt: skip
def test_a_station_with_a_missing_value_is_refused_naming_its_variable(values, simulation_window, match):  # fmt: skip
    etp = replace(station("S1", 5.0, 5.0, values or [0.0]), variable="etp")
    if not values:  # a series with no sample has no mean
        etp.data = etp.data.iloc[:0]
    with pytest.raises(ValueError, match="^Coverage check failed " + match):
        points_on_cells([etp], simulation_window=simulation_window)


@pytest.mark.parametrize(("power", "rate"), [(1.0, 12.5), (2.0, 11.0)], ids=["power-1", "power-2"])
def test_idw_weighs_the_stations_with_the_power_it_is_given(power, rate):
    stations = [station("near", 4.0, 5.0, 10.0), station("far", 8.0, 5.0, 20.0)]  # 1 m and 3 m away
    result = points_on_cells(stations, 1, 1, method="idw", idw_power=power)
    np.testing.assert_allclose(result[0], rate * MM_DAY_TO_M_S)


_L93_WKT = CRS.from_epsg(2154).to_wkt()


@pytest.mark.parametrize(
    ("station_crs", "mesh_crs", "refused"),
    [("EPSG:4326", _L93_WKT, True), ("EPSG:2154", _L93_WKT, False), ("", _L93_WKT, False), ("EPSG:4326", None, False)],
    ids=["another-crs", "same-crs-written-otherwise", "station-without-crs", "mesh-without-crs"],
)  # fmt: skip
def test_a_station_in_another_crs_than_the_mesh_is_refused(station_crs, mesh_crs, refused):
    record = station("S1", 5.0, 5.0, 8.0)
    record = replace(record, location=replace(record.location, crs=station_crs))
    match = (
        r"^The recharge station S1 is in EPSG:4326 and the mesh in EPSG:2154\. A station is never"
    )
    with pytest.raises(DataContractViolation, match=match) if refused else nullcontext():
        np.testing.assert_allclose(
            points_on_cells([record], mesh_crs=mesh_crs)[0], 8.0 * MM_DAY_TO_M_S
        )


def test_station_on_one_period_takes_the_time_mean():
    # Month-end samples of 2, 8 and 1 over 31, 29 and 31 days.
    month_ends = pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
    values = period_means(
        pd.Series([2.0, 8.0, 1.0], index=month_ends),
        period_bounds=[(pd.Timestamp("2000-01-01"), pd.Timestamp("2000-04-01"))],
        coverage_policy="error",
        label="station",
    )

    assert values.tolist() == pytest.approx([np.average([2.0, 8.0, 1.0], weights=[31, 29, 31])])
