"""Putting an observation chronicle on the stress periods of a run, and the time axis of a run.

A simulation stamp is the END of its period, an observation is stamped at the
START of what it averages. A run takes its stamps from the solver ``/time`` axis,
and falls back on the period bounds of its facts only when no axis was stored.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.period_aggregation import observation_step
from hydromodpy.results.derive.catchment_aggregation import series_time_index
from hydromodpy.results.derive.time_alignment import (
    observed_on_simulation_index,
    solver_time_index,
)
from hydromodpy.results.derive.views import _time_index


def _block_daily(blocks: list[tuple[str, str, float]]) -> pd.Series:
    """Daily series worth a constant on each half-open ``[start, end)`` block."""
    parts = [
        pd.Series(value, index=pd.date_range(start, end, freq="D", inclusive="left"))
        for start, end, value in blocks
    ]
    return pd.concat(parts).rename("obs")


def test_daily_binned_on_closed_period() -> None:
    # Two monthly stamps: [2019-12-01, 2020-01-01) and [2020-01-01, 2020-02-01).
    # The first period holds no observation, the second holds the three January
    # days. The centered reading answered 2.0 and 12.0, mixing February in.
    obs = pd.Series(
        [1.0, 3.0, 10.0, 14.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-31", "2020-02-02"]),
    )
    sim_index = pd.DatetimeIndex(["2020-01-01", "2020-02-01"])

    aligned = observed_on_simulation_index(obs, sim_index)

    assert aligned.index.equals(sim_index)
    assert np.isnan(aligned.iloc[0])
    assert aligned.iloc[1] == pytest.approx(14.0 / 3.0)


def test_two_samples_leave_gap() -> None:
    # One spacing cannot tell a step from a gap, so February stays empty.
    two = pd.Series([1.0, 3.0], index=pd.DatetimeIndex(["2003-01-01", "2003-03-01"]))
    stamps = pd.DatetimeIndex(["2003-02-01", "2003-03-01", "2003-04-01"])

    aligned = observed_on_simulation_index(two, stamps, start="2003-01-01")

    assert observation_step(two.index) is None
    assert aligned.iloc[0] == 1.0
    assert np.isnan(aligned.iloc[1])
    assert aligned.iloc[2] == 3.0


def test_monthly_step_with_gap() -> None:
    step = observation_step(pd.DatetimeIndex(["2020-01-01", "2020-02-01", "2020-04-01"]))

    assert pd.Timestamp("2020-02-01") + step == pd.Timestamp("2020-03-01")


def test_lone_stamp_takes_mean() -> None:
    # The stamp 2001-01-01 closes a steady period whose start is unknown. The
    # period cannot be read from one stamp, so the whole chronicle is averaged,
    # (1 + 2 + 7) / 3, and not its last day, 7. Every calibration path passes
    # the start it knows instead.
    obs = pd.Series([1.0, 2.0, 7.0], index=pd.date_range("2000-12-30", periods=3, freq="D"))

    aligned = observed_on_simulation_index(obs, pd.DatetimeIndex(["2001-01-01"]))

    assert aligned.tolist() == [pytest.approx(10.0 / 3.0)]


def stored_time_axis(times, *, fails=False, window=(None, None, None)):
    """A run store reduced to the ``/time`` axis of its field store and its facts."""
    start, end, unit = window

    @contextmanager
    def open_zarr(sim_id):
        if fails:
            raise RuntimeError("zarr open failed")
        yield SimpleNamespace(read_time=lambda: times)

    facts = SimpleNamespace(period_start=start, period_end=end, time_unit=unit)
    return SimpleNamespace(facts=facts, open_zarr=open_zarr)


def run_with_period_only(row):
    """A run with no solver time axis, only the period bounds of its catalog row."""
    return SimpleNamespace(_catalog=object(), _sim_id="sim", _load_row=lambda: row)


def test_no_axis_when_store_fails() -> None:
    days = np.datetime64("2019-01-02") + np.arange(5).astype("timedelta64[D]")

    assert solver_time_index(stored_time_axis(days, fails=True), "sim", 5) is None


def test_series_without_period_refused() -> None:
    with pytest.raises(RuntimeError, match="period_start/period_end"):
        series_time_index(stored_time_axis(None), "sim", 5)


def test_daily_fallback_stamps() -> None:
    run = run_with_period_only(
        {"period_start": "2019-01-01", "period_end": "2019-01-06", "time_unit": "day"}
    )

    index = _time_index(run, 5)

    assert list(index) == list(pd.date_range("2019-01-02", "2019-01-06", freq="D"))


def test_view_without_bounds_refused() -> None:
    run = run_with_period_only({"period_start": None, "period_end": None})

    with pytest.raises(RuntimeError, match="no /time axis"):
        _time_index(run, 3)
