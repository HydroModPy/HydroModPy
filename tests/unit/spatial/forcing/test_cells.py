"""The forcing of every cell of a mesh, :mod:`hydromodpy.spatial.forcing.cells`.

MODFLOW orders rows from north to south and ``yoff`` is the southern edge. The
forcing reads the centres of the cells, so a raster that rises to the north
must give a recharge that falls with the row. The start and end of every stress
period are read here too.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.spatial.forcing.cells import (
    discretize_fields_on_cells,
    discretize_points_on_cells,
    spatial_mean_from_fields,
    stress_period_bounds,
)
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from tests.unit.spatial.forcing.forcing_cases import (
    MM_DAY_TO_M_S,
    PIXEL,
    centres,
    daily_field,
    field_record,
    grid_source,
    pixel_axes,
    static_field,
    station,
    window,
)

pytestmark = pytest.mark.fast

DAYS = 60
"""A 60-day daily record on a six-month window ends four months early."""

JAN, FEB, MAR, APR, JUL = (pd.Timestamp(f"2020-{month:02d}-01") for month in (1, 2, 3, 4, 7))


def test_a_source_without_field_gives_zero_on_every_period():
    result = discretize_fields_on_cells(load_result=LoadResult(), centers=centres(4, 5), nper=3)

    assert sorted(result) == [0, 1, 2]
    for kper in range(3):
        assert result[kper].shape == (20,)
        assert np.all(result[kper] == 0.0)


@pytest.mark.parametrize(
    "discretize",
    [discretize_fields_on_cells, discretize_points_on_cells],
    ids=["fields", "points"],
)
@pytest.mark.parametrize("shape", [(6,), (3, 3)], ids=["flat", "three-columns"])
def test_centres_that_are_not_pairs_are_refused(discretize, shape):
    with pytest.raises(ValueError, match=r"centers must have shape \(n_cells, 2\)"):
        discretize(load_result=LoadResult(), centers=np.zeros(shape), nper=1)


def test_each_cell_takes_the_pixel_under_its_centre():
    x, y = pixel_axes(3, 4)
    rows = np.repeat(np.array([[1.0], [2.0], [3.0]]), 4, axis=1)

    result = discretize_fields_on_cells(
        load_result=grid_source(rows, x, y), centers=centres(3, 4), nper=1
    )

    np.testing.assert_allclose(result[0], rows.ravel() * MM_DAY_TO_M_S, rtol=1e-6)


def _solver_mesh_centres(nrow: int, ncol: int, xoff: float, yoff: float) -> np.ndarray:
    mesh = solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.zeros((nrow, ncol)),
        botm=np.full((1, nrow, ncol), -10.0),
        dx=PIXEL,
        dy=PIXEL,
        xoff=xoff,
        yoff=yoff,
    )
    return mesh.cell_centroids()


def test_the_centres_of_a_mesh_built_from_arrays_put_row_zero_north():
    nrow, ncol, xoff, yoff = 3, 2, 1000.0, 2000.0

    grid = _solver_mesh_centres(nrow, ncol, xoff, yoff).reshape(nrow, ncol, 2)

    assert np.all(np.diff(grid[:, 0, 1]) < 0.0)
    assert grid[0, 0, 1] == pytest.approx(yoff + nrow * PIXEL - PIXEL / 2.0)
    assert grid[-1, 0, 1] == pytest.approx(yoff + PIXEL / 2.0)
    assert grid[0, 0, 0] == pytest.approx(xoff + PIXEL / 2.0)


def test_a_raster_that_rises_to_the_north_gives_a_recharge_that_falls_with_the_row():
    nrow, ncol, xoff, yoff = 3, 2, 1000.0, 2000.0
    cells = _solver_mesh_centres(nrow, ncol, xoff, yoff)
    x = xoff + (np.arange(ncol) + 0.5) * PIXEL
    y = yoff + (np.arange(nrow)[::-1] + 0.5) * PIXEL
    northing = np.repeat(y[:, None], ncol, axis=1)

    result = discretize_fields_on_cells(
        load_result=grid_source(northing, x, y), centers=cells, nper=1
    )

    recharge = result[0].reshape(nrow, ncol)
    assert np.all(np.diff(recharge[:, 0]) < 0.0)
    np.testing.assert_allclose(recharge, cells.reshape(nrow, ncol, 2)[..., 1] * MM_DAY_TO_M_S)


@pytest.mark.parametrize(
    ("records", "simulation_window", "expected"),
    [
        ([static_field(2, 2, 10.0), static_field(2, 2, 20.0)], None, 15.0),
        (
            [daily_field(2, 2, [value] * 31) for value in (1.0, 2.0, 6.0)],
            window("2020-01-01", "2020-01-31", coverage_policy="error"),
            3.0,
        ),
    ],
    ids=["two-static-grids", "three-daily-grids"],
)
def test_records_on_one_period_are_averaged_with_equal_weights(
    records, simulation_window, expected
):
    result = discretize_fields_on_cells(
        load_result=LoadResult(fields=records),
        centers=centres(2, 2),
        nper=1,
        simulation_window=simulation_window,
    )

    np.testing.assert_allclose(result[0], expected * MM_DAY_TO_M_S, rtol=1e-8)


def test_a_period_past_the_last_slice_gets_zero_without_a_window():
    result = discretize_fields_on_cells(
        load_result=LoadResult(fields=[daily_field(2, 2, [1.0, 3.0])]),
        centers=centres(2, 2),
        nper=3,
    )

    np.testing.assert_allclose(result[1], 3.0 * MM_DAY_TO_M_S)
    assert np.all(result[2] == 0.0)


@pytest.mark.parametrize(
    ("discretize", "source"),
    [
        (discretize_fields_on_cells, LoadResult(fields=[daily_field(2, 2, [2.0] * DAYS)])),
        (discretize_points_on_cells, LoadResult(points=[station("S1", 5.0, 5.0, 2.0, days=DAYS)])),
    ],
    ids=["grid", "station"],
)
def test_a_record_that_ends_early_stops_the_run_under_error(discretize, source):
    with pytest.raises(ValueError, match="does not cover stress period"):
        discretize(
            load_result=source,
            centers=centres(2, 2),
            nper=6,
            simulation_window=window("2020-01-01", "2020-06-30", coverage_policy="error"),
        )


def test_a_source_without_field_has_no_spatial_mean():
    assert spatial_mean_from_fields(LoadResult()) is None


def test_a_source_whose_fields_hold_no_variable_has_no_spatial_mean():
    assert spatial_mean_from_fields(LoadResult(fields=[field_record(xr.Dataset())])) is None


def test_two_fields_give_the_mean_of_their_spatial_means_day_by_day():
    records = [daily_field(2, 2, [1.0, 2.0, 3.0]), daily_field(2, 2, [3.0, 4.0, 5.0])]

    series = spatial_mean_from_fields(LoadResult(fields=records))

    np.testing.assert_allclose(series.to_numpy(), [2.0, 3.0, 4.0])


def test_without_a_window_there_is_no_period_bound():
    assert stress_period_bounds(3, None) is None


def test_a_monthly_window_gives_one_half_open_period_a_month():
    bounds = stress_period_bounds(3, window("2020-01-01", "2020-03-31"))

    assert bounds == [(JAN, FEB), (FEB, MAR), (MAR, APR)]


def test_the_periods_stop_at_the_number_the_run_asks_for():
    bounds = stress_period_bounds(2, window("2020-01-01", "2020-03-31"))

    assert bounds == [(JAN, FEB), (FEB, MAR)]


def test_a_steady_run_reads_its_one_period_over_the_whole_window():
    steady = window("2020-01-01", "2020-06-30", period_bounds=((JAN, JUL),))

    assert stress_period_bounds(1, steady) == [(JAN, JUL)]


def test_explicit_periods_stop_at_the_number_the_run_asks_for():
    explicit = window(
        "2020-01-01", "2020-03-31", period_bounds=(("2020-01-01", "2020-02-01"), (FEB, APR))
    )

    assert stress_period_bounds(1, explicit) == [(JAN, FEB)]
