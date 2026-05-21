"""Unit tests for time-dependent flow forcing aggregation."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.physics.flow.time_forcing import (
    aggregate_forcing_series,
    resolve_period_values_from_forcing,
)


def _daily_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2000-01-03"),
        step_value=1,
        step_unit="day",
        coverage_policy="error",
    )


def test_mean_forcing_uses_period_mean_and_forward_carry() -> None:
    series = pd.Series(
        [12.0, 30.0],
        index=pd.to_datetime(["2000-01-01 12:00", "2000-01-03 00:00"]),
    )

    values = aggregate_forcing_series(
        series,
        simulation_window=_daily_window(),
        label="recharge forcing",
        aggregate="mean",
    )

    assert values == [12.0, 12.0, 30.0]


def test_last_forcing_uses_latest_value_at_period_start() -> None:
    series = pd.Series(
        [4.0, 8.0, 16.0],
        index=pd.to_datetime(["1999-12-31 12:00", "2000-01-02 00:00", "2000-01-03 12:00"]),
    )

    values = aggregate_forcing_series(
        series,
        simulation_window=_daily_window(),
        label="well forcing",
        aggregate="last",
    )

    assert values == [4.0, 8.0, 8.0]


def test_csv_forcing_rejects_resolved_length_that_differs_from_nper(tmp_path) -> None:
    csv_path = tmp_path / "forcing.csv"
    csv_path.write_text(
        "date,value\n2000-01-01,1.0\n2000-01-02,2.0\n2000-01-03,3.0\n",
        encoding="utf-8",
    )
    forcing = SimpleNamespace(
        kind="csv",
        path_file=csv_path,
        sep=",",
        date_column="date",
        date_format=None,
        value_column="value",
        aggregate="mean",
    )

    with pytest.raises(
        ValueError, match="resolved forcing length \\(3\\) does not match nper \\(2\\)"
    ):
        resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=_daily_window(),
            nper=2,
            label="flow.sinks_sources.recharge",
        )
