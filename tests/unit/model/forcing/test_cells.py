"""The forcing of every cell of a mesh, :mod:`hydromodpy.model.forcing.cells`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.model.forcing.cells import discretize_fields_on_cells, discretize_points_on_cells
from tests._helpers import forcing_cases as fc
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

pytestmark = pytest.mark.fast

DAYS = 60  # a 60-day daily record on a six-month window ends four months early
JAN, FEB, MAR, APR, JUL = (pd.Timestamp(f"2020-{month:02d}-01") for month in (1, 2, 3, 4, 7))


def test_no_field_gives_zero():
    result = fc.fields_on_cells([], 4, 5, nper=3)
    assert sorted(result) == [0, 1, 2]
    assert all(result[kper].shape == (20,) and np.all(result[kper] == 0.0) for kper in range(3))


DISCRETIZE = pytest.mark.parametrize(
    "discretize", [discretize_fields_on_cells, discretize_points_on_cells], ids=["fields", "points"]
)


@DISCRETIZE
@pytest.mark.parametrize("shape", [(6,), (3, 3)], ids=["flat", "three-columns"])
def test_centres_must_be_pairs(discretize, shape):
    with pytest.raises(ValueError, match=r"centers must have shape \(n_cells, 2\)"):
        discretize(load_result=LoadResult(), centers=np.zeros(shape), nper=1, mesh_crs=None)


@DISCRETIZE
def test_mesh_crs_is_required(discretize):
    with pytest.raises(TypeError, match="mesh_crs"):
        discretize(load_result=LoadResult(), centers=np.zeros((1, 2)), nper=1)


def test_cell_takes_pixel_under_centre():
    rows = np.repeat(np.array([[1.0], [2.0], [3.0]]), 4, axis=1)
    result = discretize_fields_on_cells(
        load_result=fc.grid_source(rows, *fc.pixel_axes(3, 4)), centers=fc.centres(3, 4), nper=1,
        mesh_crs=None,
    )  # fmt: skip
    np.testing.assert_allclose(result[0], rows.ravel() * fc.MM_DAY_TO_M_S, rtol=1e-6)


def test_northing_gradient_follows_rows():
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
def test_records_averaged_equally(records, simulation_window, expected):
    result = fc.fields_on_cells(records, simulation_window=simulation_window)
    np.testing.assert_allclose(result[0], expected * fc.MM_DAY_TO_M_S, rtol=1e-8)


def test_past_last_slice_is_zero():
    result = fc.fields_on_cells([fc.daily_field(2, 2, [1.0, 3.0])], nper=3)
    np.testing.assert_allclose(result[1], 3.0 * fc.MM_DAY_TO_M_S)
    assert np.all(result[2] == 0.0)


@pytest.mark.parametrize(
    ("on_cells", "record"),
    [(fc.fields_on_cells, fc.daily_field(2, 2, [2.0] * DAYS)), (fc.points_on_cells, fc.station("S1", 5.0, 5.0, 2.0, days=DAYS))],
    ids=["grid", "station"],
)  # fmt: skip
def test_short_record_stops_under_error(on_cells, record):
    six_months = fc.window("2020-01-01", "2020-06-30", coverage_policy="error")
    with pytest.raises(ValueError, match="does not cover stress period"):
        on_cells([record], nper=6, simulation_window=six_months)


def test_grid_one_period_time_mean():
    # Month-end grids of 2, 8 and 1 mm/day over 31, 29 and 31 days, on one period.
    month_ends = pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
    one_period = (pd.Timestamp("2000-01-01"), pd.Timestamp("2000-04-01"))
    window = fc.window("2000-01-01", "2000-03-31", period_bounds=(one_period,))
    x, y = fc.pixel_axes(2, 2)
    stack = np.stack([np.full((2, 2), rate) for rate in (2.0, 8.0, 1.0)])
    record = fc.field_record(fc.grid_dataset(stack, x, y, month_ends))

    arrays = discretize_fields_on_cells(
        load_result=LoadResult(fields=[record]),
        centers=np.array([[x[0], y[0]]]),
        nper=1,
        simulation_window=window,
        mesh_crs=None,
    )

    time_mean = np.average([2.0, 8.0, 1.0], weights=[31, 29, 31])
    assert float(arrays[0][0]) == pytest.approx(time_mean * fc.MM_DAY_TO_M_S)
