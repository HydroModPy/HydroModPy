"""Putting an observation chronicle on the stress periods of a run.

A simulation stamp is the END of its period, an observation is stamped at the
START of what it averages. These tests used to read a simulation stamp as the
center of its period, or to match it to the nearest observation; both put the
observation one period late on a regular run, and they were rewritten when the
stamp convention was measured on the solvers' own ``/time`` axis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.period_aggregation import observation_step
from hydromodpy.results.derive.time_alignment import observed_on_simulation_index

MONTH_ENDS_2000 = pd.date_range("2000-02-01", "2001-01-01", freq="MS")


def _block_daily(blocks: list[tuple[str, str, float]]) -> pd.Series:
    """Daily series worth a constant on each half-open ``[start, end)`` block."""
    parts = [
        pd.Series(value, index=pd.date_range(start, end, freq="D", inclusive="left"))
        for start, end, value in blocks
    ]
    return pd.concat(parts).rename("obs")


def test_observed_daily_values_are_binned_on_the_period_each_stamp_closes() -> None:
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


def test_two_samples_do_not_stand_for_the_period_between_them() -> None:
    # One spacing cannot tell a step from a gap, so February stays empty.
    two = pd.Series([1.0, 3.0], index=pd.DatetimeIndex(["2003-01-01", "2003-03-01"]))
    stamps = pd.DatetimeIndex(["2003-02-01", "2003-03-01", "2003-04-01"])

    aligned = observed_on_simulation_index(two, stamps, start="2003-01-01")

    assert observation_step(two.index) is None
    assert aligned.iloc[0] == 1.0
    assert np.isnan(aligned.iloc[1])
    assert aligned.iloc[2] == 3.0


def test_a_monthly_chronicle_with_a_gap_still_steps_in_months() -> None:
    step = observation_step(pd.DatetimeIndex(["2020-01-01", "2020-02-01", "2020-04-01"]))

    assert pd.Timestamp("2020-02-01") + step == pd.Timestamp("2020-03-01")


def test_a_lone_steady_stamp_without_its_start_takes_the_whole_chronicle_mean() -> None:
    # The stamp 2001-01-01 closes a steady period whose start is unknown. The
    # period cannot be read from one stamp, so the whole chronicle is averaged,
    # (1 + 2 + 7) / 3, and not its last day, 7. Every calibration path passes
    # the start it knows instead.
    obs = pd.Series([1.0, 2.0, 7.0], index=pd.date_range("2000-12-30", periods=3, freq="D"))

    aligned = observed_on_simulation_index(obs, pd.DatetimeIndex(["2001-01-01"]))

    assert aligned.tolist() == [pytest.approx(10.0 / 3.0)]
