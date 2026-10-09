"""One coverage rule for a series, a station and a grid.

Before, a series was carried forward before ``coverage_policy`` could see it,
so a record that ended early was extended in silence; a grid applied the policy
and filled with the slice nearest to the period start; and several grids were
merged pairwise with weights 1/2 and 1/2. The rule now lives in
``hydromodpy.core.time.coverage`` and every reader goes through it.
"""

from __future__ import annotations

import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time import build_simulation_time_boundaries
from hydromodpy.core.time.coverage import samples_by_period
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.time_forcing import aggregate_forcing_series
from hydromodpy.physics.forcing.time_alignment import align_forcing_series_to_simulation_window
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
    discretize_fields_on_sgrid,
    discretize_points_on_sgrid,
)

from ._test_sgrid_field_discretization_builders import (
    MM_DAY_TO_M_S,
    _make_sgrid,
    _make_simulation_window,
    _make_temporal_field_record,
)

# A 60-day daily record on a six-month window: four months after its end.
DAYS = 60


def _daily_series(n_days: int = DAYS, value: float = 2.0) -> pd.Series:
    return pd.Series(value, index=pd.date_range("2020-01-01", periods=n_days, freq="D"))


def _point_record(n_days: int = DAYS, value: float = 2.0) -> PointRecord:
    dates = pd.date_range("2020-01-01", periods=n_days, freq="D")
    return PointRecord(
        station_id="S1",
        variable="recharge",
        source="test",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": np.full(n_days, value)}),
        date_start=datetime(2020, 1, 1),
        date_end=dates[-1].to_pydatetime(),
        location=StationLocation(id="S1", x=5.0, y=5.0, crs="EPSG:2154"),
    )


def _six_months(policy: str):
    return _make_simulation_window("2020-01-01", "2020-06-30", coverage_policy=policy)


def test_a_series_that_ends_early_stops_the_run_under_error():
    with pytest.raises(ValueError, match="does not cover stress period"):
        align_forcing_series_to_simulation_window(
            _daily_series(), simulation_window=_six_months("error"), label="recharge"
        )


def test_series_station_and_grid_give_the_same_verdict():
    window = _six_months("error")
    with pytest.raises(ValueError, match="does not cover stress period"):
        discretize_fields_on_sgrid(
            load_result=LoadResult(fields=[_make_temporal_field_record(2, 2, [2.0] * DAYS)]),
            sgrid=_make_sgrid(2, 2),
            nper=6,
            simulation_window=window,
        )
    with pytest.raises(ValueError, match="does not cover stress period"):
        discretize_points_on_sgrid(
            load_result=LoadResult(points=[_point_record()]),
            sgrid=_make_sgrid(2, 2),
            nper=6,
            simulation_window=window,
        )


def test_warn_warns_once_and_fills_with_the_last_sample():
    series = _daily_series()
    series.iloc[-1] = 8.0
    with pytest.warns(UserWarning, match="does not cover stress period") as caught:
        aligned = align_forcing_series_to_simulation_window(
            series, simulation_window=_six_months("warn"), label="recharge"
        )
    assert len([w for w in caught if "does not cover" in str(w.message)]) == 1
    np.testing.assert_allclose(aligned.iloc[2:].to_numpy(), 8.0)


def test_daily_samples_cover_hourly_periods():
    window = _make_simulation_window(
        "2020-01-01", "2020-01-02 23:00", step_value=6, step_unit="hour", coverage_policy="error"
    )
    series = pd.Series([1.0, 3.0], index=pd.to_datetime(["2020-01-01", "2020-01-02"]))

    aligned = align_forcing_series_to_simulation_window(
        series, simulation_window=window, label="rain"
    )

    np.testing.assert_allclose(aligned.to_numpy(), [1.0] * 4 + [3.0] * 4)


def test_a_gap_inside_the_record_is_covered_by_the_sample_in_force():
    window = _make_simulation_window("2000-01-01", "2000-03-31", coverage_policy="error")
    series = pd.Series([2.0, 6.0], index=pd.to_datetime(["2000-01-01", "2000-03-01"]))

    aligned = align_forcing_series_to_simulation_window(
        series, simulation_window=window, label="recharge"
    )

    np.testing.assert_allclose(aligned.to_numpy(), [2.0, 2.0, 6.0])


def test_the_last_sample_stands_for_one_step_of_the_record():
    # Monthly stamps at the month start: December is covered by its own sample.
    stamps = pd.date_range("2000-01-01", "2000-12-01", freq="MS")
    window = _make_simulation_window("2000-01-01", "2000-12-31", step_value=1, step_unit="day")
    periods = samples_by_period(stamps, build_simulation_time_boundaries(window))

    assert periods.uncovered == ()


def test_a_period_before_the_record_follows_the_policy():
    window = _make_simulation_window("2000-01-01", "2000-02-29", coverage_policy="ignore")
    series = pd.Series([5.0], index=pd.to_datetime(["2000-02-01"]))

    aligned = align_forcing_series_to_simulation_window(
        series, simulation_window=window, label="recharge"
    )

    np.testing.assert_allclose(aligned.to_numpy(), [5.0, 5.0])
    with pytest.raises(ValueError, match="does not cover stress period"):
        align_forcing_series_to_simulation_window(
            series,
            simulation_window=_make_simulation_window(
                "2000-01-01", "2000-02-29", coverage_policy="error"
            ),
            label="recharge",
        )


def test_a_grid_gap_takes_the_slice_in_force_not_the_nearest_one():
    # Daily slices on 6-hour periods: 18:00 is nearer to the next day's slice,
    # but the slice in force is the one of its own day.
    record = _make_temporal_field_record(1, 1, [1.0, 3.0])
    window = _make_simulation_window(
        "2020-01-01", "2020-01-02 23:00", step_value=6, step_unit="hour", coverage_policy="error"
    )

    arrays = discretize_fields_on_sgrid(
        load_result=LoadResult(fields=[record]),
        sgrid=_make_sgrid(1, 1),
        nper=8,
        simulation_window=window,
    )

    got = [float(arrays[k].ravel()[0]) / MM_DAY_TO_M_S for k in range(8)]
    np.testing.assert_allclose(got, [1.0] * 4 + [3.0] * 4)


def test_three_grids_on_one_period_are_averaged_with_equal_weights():
    records = [_make_temporal_field_record(1, 1, [value] * 31) for value in (1.0, 2.0, 6.0)]
    window = _make_simulation_window("2020-01-01", "2020-01-31", coverage_policy="error")

    arrays = discretize_fields_on_sgrid(
        load_result=LoadResult(fields=records),
        sgrid=_make_sgrid(1, 1),
        nper=1,
        simulation_window=window,
    )

    assert float(arrays[0].ravel()[0]) / MM_DAY_TO_M_S == pytest.approx(3.0)


def test_a_state_record_read_with_last_is_not_a_coverage_question():
    window = _six_months("error")
    series = pd.Series([4.0], index=pd.to_datetime(["2019-06-01"]))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        values = aggregate_forcing_series(
            series, simulation_window=window, label="well", aggregate="last"
        )

    assert values == [4.0] * 6


@pytest.mark.parametrize("unit", ["s", "ms", "us"])
def test_a_record_in_another_time_unit_takes_the_same_samples(unit):
    # A parquet or DuckDB read gives datetime64[us]; the stamps must still sort
    # against the period edges, not all before them.
    window = _make_simulation_window("2020-01-01", "2020-03-31", coverage_policy="error")
    index = pd.date_range("2020-01-01", "2020-03-31", freq="D").as_unit(unit)
    series = pd.Series(np.arange(len(index), dtype=float), index=index)

    aligned = align_forcing_series_to_simulation_window(
        series, simulation_window=window, label="recharge"
    )

    np.testing.assert_allclose(aligned.to_numpy(), [15.0, 45.0, 75.0])
    periods = samples_by_period(index, build_simulation_time_boundaries(window))
    assert [p.size for p in periods.inside] == [31, 29, 31]


def test_a_record_in_seconds_that_ends_early_is_still_refused():
    index = pd.date_range("2020-01-01", periods=DAYS, freq="D").as_unit("s")
    with pytest.raises(ValueError, match="does not cover stress period"):
        align_forcing_series_to_simulation_window(
            pd.Series(2.0, index=index), simulation_window=_six_months("error"), label="recharge"
        )
