from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.results.time_alignment import (
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
