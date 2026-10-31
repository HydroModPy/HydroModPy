"""The forcing of every cell of a mesh, :mod:`hydromodpy.spatial.forcing.cells`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.spatial.forcing.cells import (
    discretize_fields_on_cells,
    discretize_points_on_cells,
    stress_period_bounds,
)
from tests._helpers import forcing_cases as fc
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

pytestmark = pytest.mark.fast

DAYS = 60  # a 60-day daily record on a six-month window ends four months early
JAN, FEB, MAR, APR, JUL = (pd.Timestamp(f"2020-{month:02d}-01") for month in (1, 2, 3, 4, 7))


def test_a_source_without_field_gives_zero_on_every_period():
    result = fc.fields_on_cells([], 4, 5, nper=3)
    assert sorted(result) == [0, 1, 2]
    assert all(result[kper].shape == (20,) and np.all(result[kper] == 0.0) for kper in range(3))


DISCRETIZE = pytest.mark.parametrize(
    "discretize", [discretize_fields_on_cells, discretize_points_on_cells], ids=["fields", "points"]
)


@DISCRETIZE
@pytest.mark.parametrize("shape", [(6,), (3, 3)], ids=["flat", "three-columns"])
def test_centres_that_are_not_pairs_are_refused(discretize, shape):
    with pytest.raises(ValueError, match=r"centers must have shape \(n_cells, 2\)"):
        discretize(load_result=LoadResult(), centers=np.zeros(shape), nper=1, mesh_crs=None)


@DISCRETIZE
def test_the_mesh_crs_is_required_so_no_caller_skips_the_crs_check(discretize):
    with pytest.raises(TypeError, match="mesh_crs"):
        discretize(load_result=LoadResult(), centers=np.zeros((1, 2)), nper=1)


def test_each_cell_takes_the_pixel_under_its_centre():
    rows = np.repeat(np.array([[1.0], [2.0], [3.0]]), 4, axis=1)
    result = discretize_fields_on_cells(
        load_result=fc.grid_source(rows, *fc.pixel_axes(3, 4)), centers=fc.centres(3, 4), nper=1,
        mesh_crs=None,
    )  # fmt: skip
    np.testing.assert_allclose(result[0], rows.ravel() * fc.MM_DAY_TO_M_S, rtol=1e-6)


def test_a_raster_that_rises_to_the_north_gives_a_recharge_that_falls_with_the_row():
    nrow, ncol, xoff, yoff = 3, 2, 1000.0, 2000.0
    cells = solver_mesh_from_structured_arrays(
        nrow=nrow, ncol=ncol, top=np.zeros((nrow, ncol)), botm=np.full((1, nrow, ncol), -10.0),
        dx=fc.PIXEL, dy=fc.PIXEL, xoff=xoff, yoff=yoff,
    ).cell_centers()  # fmt: skip
    grid = cells.reshape(nrow, ncol, 2)
    x = xoff + (np.arange(ncol) + 0.5) * fc.PIXEL
    y = yoff + (np.arange(nrow)[::-1] + 0.5) * fc.PIXEL
    northing = np.repeat(y[:, None], ncol, axis=1)

    source = fc.grid_source(northing, x, y)
    result = discretize_fields_on_cells(load_result=source, centers=cells, nper=1, mesh_crs=None)

    assert np.all(np.diff(grid[:, 0, 1]) < 0.0)
    assert grid[0, 0, 1] == pytest.approx(yoff + nrow * fc.PIXEL - fc.PIXEL / 2.0)
    assert grid[-1, 0, 1] == pytest.approx(yoff + fc.PIXEL / 2.0)
    assert grid[0, 0, 0] == pytest.approx(xoff + fc.PIXEL / 2.0)
    recharge = result[0].reshape(nrow, ncol)
    assert np.all(np.diff(recharge[:, 0]) < 0.0)
    np.testing.assert_allclose(recharge, grid[..., 1] * fc.MM_DAY_TO_M_S)


@pytest.mark.parametrize(
    ("records", "simulation_window", "expected"),
    [
        ([fc.static_field(2, 2, 10.0), fc.static_field(2, 2, 20.0)], None, 15.0),
        ([fc.daily_field(2, 2, [value] * 31) for value in (1.0, 2.0, 6.0)],
         fc.window("2020-01-01", "2020-01-31", coverage_policy="error"), 3.0),
    ],
    ids=["two-static-grids", "three-daily-grids"],
)  # fmt: skip
def test_records_on_one_period_are_averaged_with_equal_weights(
    records, simulation_window, expected
):
    result = fc.fields_on_cells(records, simulation_window=simulation_window)
    np.testing.assert_allclose(result[0], expected * fc.MM_DAY_TO_M_S, rtol=1e-8)


def test_a_period_past_the_last_slice_gets_zero_without_a_window():
    result = fc.fields_on_cells([fc.daily_field(2, 2, [1.0, 3.0])], nper=3)
    np.testing.assert_allclose(result[1], 3.0 * fc.MM_DAY_TO_M_S)
    assert np.all(result[2] == 0.0)


@pytest.mark.parametrize(
    ("on_cells", "record"),
    [(fc.fields_on_cells, fc.daily_field(2, 2, [2.0] * DAYS)), (fc.points_on_cells, fc.station("S1", 5.0, 5.0, 2.0, days=DAYS))],
    ids=["grid", "station"],
)  # fmt: skip
def test_a_record_that_ends_early_stops_the_run_under_error(on_cells, record):
    six_months = fc.window("2020-01-01", "2020-06-30", coverage_policy="error")
    with pytest.raises(ValueError, match="does not cover stress period"):
        on_cells([record], nper=6, simulation_window=six_months)


@pytest.mark.parametrize(
    ("nper", "simulation_window", "expected"),
    [
        (3, None, None),
        (3, fc.window("2020-01-01", "2020-03-31"), [(JAN, FEB), (FEB, MAR), (MAR, APR)]),
        (2, fc.window("2020-01-01", "2020-03-31"), [(JAN, FEB), (FEB, MAR)]),
        (1, fc.window("2020-01-01", "2020-06-30", period_bounds=((JAN, JUL),)), [(JAN, JUL)]),
        (1, fc.window("2020-01-01", "2020-03-31", period_bounds=(("2020-01-01", "2020-02-01"), (FEB, APR))),
         [(JAN, FEB)]),
    ],
    ids=["no-window-no-bound", "monthly-half-open-periods", "stop-at-the-run-periods",
         "steady-whole-window", "explicit-stop-at-the-run-periods"],
)  # fmt: skip
def test_the_periods_of_a_window_are_half_open_and_stop_at_the_run(
    nper, simulation_window, expected
):
    assert stress_period_bounds(nper, simulation_window) == expected
