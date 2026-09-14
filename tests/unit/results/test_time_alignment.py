from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.core.time.period_aggregation import period_mean_on_index
from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    observed_on_simulation_index,
)


def test_observed_daily_values_are_binned_on_simulation_periods() -> None:
    obs = pd.Series(
        [1.0, 3.0, 10.0, 14.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-31", "2020-02-02"]),
    )
    sim_index = pd.DatetimeIndex(["2020-01-01", "2020-02-01"])

    aligned = observed_on_simulation_index(obs, sim_index)

    assert aligned.index.equals(sim_index)
    assert aligned.iloc[0] == pytest.approx(2.0)
    assert aligned.iloc[1] == pytest.approx(12.0)


def test_nearest_alignment_uses_merge_asof_without_length_truncation() -> None:
    obs = pd.Series(
        [10.0, 20.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-03"]),
    )
    sim = pd.Series(
        [11.0, 19.0, 30.0],
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-03", "2020-01-05"]),
    )

    paired = align_observed_simulated(obs, sim, dropna=False)

    assert list(paired.columns) == ["obs", "sim"]
    assert len(paired) == 3
    assert paired["obs"].tolist() == [10.0, 20.0, 20.0]


def _block_daily(blocks: list[tuple[str, str, float]]) -> pd.Series:
    """Daily series worth a constant on each half-open ``[start, end)`` block."""
    parts = [
        pd.Series(value, index=pd.date_range(start, end, freq="D", inclusive="left"))
        for start, end, value in blocks
    ]
    return pd.concat(parts).rename("runoff")


def test_a_non_uniform_simulation_index_reads_its_own_period_edges() -> None:
    # Three unevenly spaced stamps, 10 then 30 days apart. A period reaches
    # halfway to each neighbour, so the periods are exactly
    #   2000-01-06 .. 2000-01-15   10 days, every one worth 2.0
    #   2000-01-16 .. 2000-02-04   20 days, every one worth 5.0
    #   2000-02-05 .. 2000-03-05   30 days, every one worth 9.0
    # and each period mean is one of those constants, by construction. Cutting
    # every bin at a constant half of the MEDIAN spacing (10 days) mixes the
    # blocks and answers 3.0 and 8.33 instead.
    obs = _block_daily(
        [
            ("2000-01-06", "2000-01-16", 2.0),
            ("2000-01-16", "2000-02-05", 5.0),
            ("2000-02-05", "2000-03-06", 9.0),
        ]
    )
    sim_index = pd.DatetimeIndex(["2000-01-11", "2000-01-21", "2000-02-20"])

    aligned = observed_on_simulation_index(obs, sim_index)

    assert aligned.index.equals(sim_index)
    assert aligned.tolist() == pytest.approx([2.0, 5.0, 9.0])


def test_the_alignment_rule_is_the_one_written_in_core_time() -> None:
    # Same input, the two entry points of the single rule. They used to answer
    # differently on a non-uniform index: 100 of the 120 monthly periods of the
    # shipped Nancon stage 2 disagreed, up to 72 per cent.
    obs = _block_daily(
        [
            ("2000-01-06", "2000-01-16", 2.0),
            ("2000-01-16", "2000-02-05", 5.0),
            ("2000-02-05", "2000-03-06", 9.0),
        ]
    )
    sim_index = pd.DatetimeIndex(["2000-01-11", "2000-01-21", "2000-02-20"])

    aligned = observed_on_simulation_index(obs, sim_index)
    from_core = period_mean_on_index(obs, sim_index)

    assert aligned.tolist() == pytest.approx([2.0, 5.0, 9.0])
    assert from_core.tolist() == pytest.approx([2.0, 5.0, 9.0])


def test_observations_coarser_than_the_run_keep_the_nearest_sample() -> None:
    # A monthly gauge on a daily run: a per-period mean would leave 29 of every
    # 30 periods empty, so each stamp takes the nearest sample within one step
    # and the days beyond that reach stay gaps.
    obs = pd.Series([4.0, 8.0], index=pd.DatetimeIndex(["2020-01-15", "2020-02-15"]))
    sim_index = pd.date_range("2020-01-14", periods=4, freq="D")

    aligned = observed_on_simulation_index(obs, sim_index)

    assert aligned.iloc[:3].tolist() == pytest.approx([4.0, 4.0, 4.0])
    assert pd.isna(aligned.iloc[3])
