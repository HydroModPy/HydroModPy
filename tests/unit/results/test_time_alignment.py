"""Putting an observation chronicle on the stress periods of a run.

A simulation stamp is the END of its period, an observation is stamped at the
START of what it averages. These tests used to read a simulation stamp as the
centre of its period, or to match it to the nearest observation; both put the
observation one period late on a regular run, and they were rewritten when the
stamp convention was measured on the solvers' own ``/time`` axis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.period_aggregation import observation_step, period_mean_on_index
from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    observed_on_simulation_index,
)

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
    # days. The centred reading answered 2.0 and 12.0, mixing February in.
    obs = pd.Series(
        [1.0, 3.0, 10.0, 14.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-31", "2020-02-02"]),
    )
    sim_index = pd.DatetimeIndex(["2020-01-01", "2020-02-01"])

    aligned = observed_on_simulation_index(obs, sim_index)

    assert aligned.index.equals(sim_index)
    assert np.isnan(aligned.iloc[0])
    assert aligned.iloc[1] == pytest.approx(14.0 / 3.0)


def test_a_monthly_run_on_a_daily_chronicle_gets_the_calendar_monthly_means() -> None:
    # Constant per month, value = month number. February 2000 is a leap month.
    index = pd.date_range("2000-01-01", "2000-12-31", freq="D")
    obs = pd.Series(index.month.astype("float64"), index=index)

    aligned = observed_on_simulation_index(obs, MONTH_ENDS_2000)

    assert aligned.tolist() == [float(m) for m in range(1, 13)]


def test_a_monthly_run_on_a_monthly_chronicle_takes_each_month_unchanged() -> None:
    # A QmM stamped at its month start falls in the period its month is. The
    # nearest-sample reading took the next month's value, a full month late.
    qmm = pd.Series(np.arange(1.0, 13.0), index=pd.date_range("2000-01-01", periods=12, freq="MS"))

    aligned = observed_on_simulation_index(qmm, MONTH_ENDS_2000)

    assert aligned.tolist() == qmm.tolist()


def test_a_daily_run_on_a_daily_chronicle_is_not_shifted() -> None:
    obs = pd.Series(np.arange(10.0), index=pd.date_range("2000-01-01", periods=10, freq="D"))
    sim_index = pd.date_range("2000-01-02", periods=10, freq="D")

    aligned = observed_on_simulation_index(obs, sim_index)

    assert aligned.tolist() == obs.tolist()


def test_same_frequency_series_pair_without_length_truncation() -> None:
    # Every second day. The period closed on 2020-01-01 holds no observation
    # and none before it, so it stays a gap; the old nearest-sample rule paired
    # each stamp with the observation made AT the stamp, one period late.
    obs = pd.Series([10.0, 20.0], index=pd.DatetimeIndex(["2020-01-01", "2020-01-03"]))
    sim = pd.Series(
        [11.0, 19.0, 30.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-03", "2020-01-05"]),
    )

    paired = align_observed_simulated(obs, sim, dropna=False)

    assert list(paired.columns) == ["obs", "sim"]
    assert len(paired) == 3
    assert np.isnan(paired["obs"].iloc[0])
    assert paired["obs"].iloc[1:].tolist() == [10.0, 20.0]


def test_a_non_uniform_simulation_index_reads_its_own_period_edges() -> None:
    # Stamps 10 then 30 days apart, first period started at 2000-01-01. The
    # periods are [01-01, 01-11), [01-11, 01-21), [01-21, 02-20), each one a
    # constant block by construction.
    obs = _block_daily(
        [
            ("2000-01-01", "2000-01-11", 2.0),
            ("2000-01-11", "2000-01-21", 5.0),
            ("2000-01-21", "2000-02-20", 9.0),
        ]
    )
    sim_index = pd.DatetimeIndex(["2000-01-11", "2000-01-21", "2000-02-20"])

    aligned = observed_on_simulation_index(obs, sim_index, start="2000-01-01")
    from_core = period_mean_on_index(obs, sim_index, start="2000-01-01")

    assert aligned.index.equals(sim_index)
    assert aligned.tolist() == [2.0, 5.0, 9.0]
    assert from_core.tolist() == [2.0, 5.0, 9.0]


def test_a_steady_year_then_months_is_one_rule_not_two() -> None:
    # A long first period followed by short ones used to fall to the nearest
    # sample for EVERY period, since the choice was made on median spacings.
    index = pd.date_range("1999-01-01", "2000-03-31", freq="D")
    obs = pd.Series(np.where(index.year == 1999, 7.0, index.month.astype("float64")), index=index)
    stamps = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])

    aligned = observed_on_simulation_index(obs, stamps, start="1999-01-01")

    assert aligned.tolist() == [7.0, 1.0, 2.0, 3.0]


def test_a_monthly_chronicle_on_a_daily_run_holds_its_month() -> None:
    # A QmM stands for its whole month, so every day of January takes the
    # January value and the first day of February takes February's.
    qmm = pd.Series([4.0, 8.0], index=pd.DatetimeIndex(["2020-01-01", "2020-02-01"]))
    sim_index = pd.date_range("2020-01-30", periods=4, freq="D")

    aligned = observed_on_simulation_index(qmm, sim_index)

    # Periods: [01-29, 01-30), [01-30, 01-31), [01-31, 02-01), [02-01, 02-02).
    assert aligned.tolist() == [4.0, 4.0, 4.0, 8.0]


def test_a_gap_in_a_coarse_chronicle_stays_a_gap() -> None:
    # March is missing: the February value does not reach into it.
    qmm = pd.Series(
        [1.0, 2.0, 4.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-02-01", "2020-04-01"]),
    )
    sim_index = pd.DatetimeIndex(["2020-02-16", "2020-03-02", "2020-03-16"])

    aligned = observed_on_simulation_index(qmm, sim_index, start="2020-02-15")

    assert aligned.iloc[0] == 2.0
    assert np.isnan(aligned.iloc[1])
    assert np.isnan(aligned.iloc[2])


def test_a_monthly_chronicle_with_a_gap_still_steps_in_months() -> None:
    step = observation_step(pd.DatetimeIndex(["2020-01-01", "2020-02-01", "2020-04-01"]))

    assert pd.Timestamp("2020-02-01") + step == pd.Timestamp("2020-03-01")


def test_one_steady_period_takes_the_mean_of_its_window() -> None:
    index = pd.date_range("1999-01-01", "2001-12-31", freq="D")
    obs = pd.Series(index.year.astype("float64"), index=index)

    aligned = observed_on_simulation_index(
        obs, pd.DatetimeIndex(["2001-01-01"]), start="2000-01-01"
    )

    assert aligned.tolist() == [2000.0]


def test_millisecond_stamps_from_parquet_align() -> None:
    # A simulation read back from Parquet carries millisecond stamps; the
    # nearest-sample merge refused to join them with nanosecond observations.
    obs = pd.Series(np.arange(10.0), index=pd.date_range("2000-01-01", periods=10, freq="D"))
    sim = pd.Series(
        np.ones(10), index=pd.date_range("2000-01-02", periods=10, freq="D").as_unit("ms")
    )

    paired = align_observed_simulated(obs, sim)

    assert paired["obs"].tolist() == obs.tolist()


def test_a_lone_steady_stamp_without_its_start_takes_the_whole_chronicle_mean() -> None:
    # The stamp 2001-01-01 closes a steady period whose start is unknown. The
    # period cannot be read from one stamp, so the whole chronicle is averaged,
    # (1 + 2 + 7) / 3, and not its last day, 7. Every calibration path passes
    # the start it knows instead.
    obs = pd.Series([1.0, 2.0, 7.0], index=pd.date_range("2000-12-30", periods=3, freq="D"))

    aligned = observed_on_simulation_index(obs, pd.DatetimeIndex(["2001-01-01"]))

    assert aligned.tolist() == [pytest.approx(10.0 / 3.0)]


def test_a_lone_stamp_far_from_the_record_pairs_with_nothing() -> None:
    # A 1990 record is not the mean of a 2020 steady run: the chronicle has to
    # reach the stamp before its mean stands for it.
    obs = pd.Series([1.0], index=pd.DatetimeIndex(["1990-01-01"]))

    aligned = observed_on_simulation_index(obs, pd.DatetimeIndex(["2020-01-01"]))

    assert aligned.isna().all()
