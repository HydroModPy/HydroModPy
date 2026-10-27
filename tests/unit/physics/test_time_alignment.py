"""One coverage rule for a forcing series on the stress periods.

Before, a series was carried forward before ``coverage_policy`` could see it,
so a record that ended early was extended in silence. The rule now lives in
``hydromodpy.core.time.coverage``, and
:func:`~hydromodpy.physics.forcing.time_alignment.align_forcing_series_to_simulation_window`
goes through it. The grid and the station readers of
``hydromodpy.spatial.mesh.forcing`` go through it too; their tests are in
``tests/unit/mesh/forcing``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time import ResolvedSimulationTimeWindow, build_simulation_time_boundaries
from hydromodpy.core.time.coverage import samples_by_period
from hydromodpy.physics.forcing.time_alignment import align_forcing_series_to_simulation_window

DAYS = 60
"""A 60-day daily record on a six-month window ends four months early."""


def _window(
    start: str,
    end: str,
    step_value: int = 1,
    step_unit: str = "month",
    coverage_policy: str = "ignore",
) -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
        step_value=step_value,
        step_unit=step_unit,
        coverage_policy=coverage_policy,
    )


def _daily_series(n_days: int = DAYS, value: float = 2.0) -> pd.Series:
    return pd.Series(value, index=pd.date_range("2020-01-01", periods=n_days, freq="D"))


def _six_months(policy: str) -> ResolvedSimulationTimeWindow:
    return _window("2020-01-01", "2020-06-30", coverage_policy=policy)


def test_a_series_that_ends_early_stops_the_run_under_error():
    with pytest.raises(ValueError, match="does not cover stress period"):
        align_forcing_series_to_simulation_window(
            _daily_series(), simulation_window=_six_months("error"), label="recharge"
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
    window = _window(
        "2020-01-01", "2020-01-02 23:00", step_value=6, step_unit="hour", coverage_policy="error"
    )
    series = pd.Series([1.0, 3.0], index=pd.to_datetime(["2020-01-01", "2020-01-02"]))

    aligned = align_forcing_series_to_simulation_window(
        series, simulation_window=window, label="rain"
    )

    np.testing.assert_allclose(aligned.to_numpy(), [1.0] * 4 + [3.0] * 4)


def test_a_gap_inside_the_record_is_covered_by_the_sample_in_force():
    window = _window("2000-01-01", "2000-03-31", coverage_policy="error")
    series = pd.Series([2.0, 6.0], index=pd.to_datetime(["2000-01-01", "2000-03-01"]))

    aligned = align_forcing_series_to_simulation_window(
        series, simulation_window=window, label="recharge"
    )

    np.testing.assert_allclose(aligned.to_numpy(), [2.0, 2.0, 6.0])


def test_the_last_sample_stands_for_one_step_of_the_record():
    # Monthly stamps at the month start: December is covered by its own sample.
    stamps = pd.date_range("2000-01-01", "2000-12-01", freq="MS")
    window = _window("2000-01-01", "2000-12-31", step_value=1, step_unit="day")
    periods = samples_by_period(stamps, build_simulation_time_boundaries(window))

    assert periods.uncovered == ()


def test_a_period_before_the_record_follows_the_policy():
    window = _window("2000-01-01", "2000-02-29", coverage_policy="ignore")
    series = pd.Series([5.0], index=pd.to_datetime(["2000-02-01"]))

    aligned = align_forcing_series_to_simulation_window(
        series, simulation_window=window, label="recharge"
    )

    np.testing.assert_allclose(aligned.to_numpy(), [5.0, 5.0])
    with pytest.raises(ValueError, match="does not cover stress period"):
        align_forcing_series_to_simulation_window(
            series,
            simulation_window=_window("2000-01-01", "2000-02-29", coverage_policy="error"),
            label="recharge",
        )


@pytest.mark.parametrize("unit", ["s", "ms", "us"])
def test_a_record_in_another_time_unit_takes_the_same_samples(unit):
    # A parquet or DuckDB read gives datetime64[us]; the stamps must still sort
    # against the period edges, not all before them.
    window = _window("2020-01-01", "2020-03-31", coverage_policy="error")
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
