"""Unit tests for time-dependent flow forcing aggregation."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.physics.flow.sinks_sources.wells import (
    FlowWellForcingPiecewiseConfig,
    FlowWellForcingSeasonalConfig,
)
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


def _monthly_window() -> ResolvedSimulationTimeWindow:
    # Four monthly stress periods: Jan, Feb, Mar, Apr of 2000.
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2000-04-30"),
        step_value=1,
        step_unit="month",
        coverage_policy="ignore",
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


def test_piecewise_forcing_resolves_csv_then_constant(tmp_path) -> None:
    csv_path = tmp_path / "chronicle.csv"
    csv_path.write_text(
        "date,value\n2000-01-01,10.0\n2000-02-01,20.0\n",
        encoding="utf-8",
    )
    forcing = FlowWellForcingPiecewiseConfig(
        segments=[
            {
                "start": "2000-01-01",
                "end": "2000-03-01",
                "forcing": {
                    "kind": "csv",
                    "path_file": str(csv_path),
                    "date_column": "date",
                    "value_column": "value",
                },
            },
            {"start": "2000-03-01", "forcing": {"kind": "constant", "value": 99.0}},
        ],
    )

    values = resolve_period_values_from_forcing(
        forcing=forcing,
        simulation_window=_monthly_window(),
        nper=4,
        label="flow.sinks_sources.lakes.lac0.inflow",
    )

    # Jan/Feb come from the csv chronicle, Mar/Apr from the constant segment.
    assert values == [10.0, 20.0, 99.0, 99.0]


def test_piecewise_forcing_rejects_uncovered_period() -> None:
    forcing = FlowWellForcingPiecewiseConfig(
        segments=[{"start": "2000-03-01", "forcing": {"kind": "constant", "value": 1.0}}],
    )

    with pytest.raises(ConfigError, match="do not cover every stress period"):
        resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=_monthly_window(),
            nper=4,
            label="flow.sinks_sources.lakes.lac0.inflow",
        )


def test_seasonal_forcing_by_month_maps_winter_and_summer() -> None:
    forcing = FlowWellForcingSeasonalConfig(
        by_month={
            1: 5.0,
            2: 5.0,
            3: 8.0,
            4: 8.0,
            5: 8.0,
            6: 8.0,
            7: 8.0,
            8: 8.0,
            9: 8.0,
            10: 8.0,
            11: 8.0,
            12: 5.0,
        },
    )

    values = resolve_period_values_from_forcing(
        forcing=forcing,
        simulation_window=_monthly_window(),
        nper=4,
        label="well forcing",
    )

    # Jan/Feb take the winter value, Mar/Apr the spring value.
    assert values == [5.0, 5.0, 8.0, 8.0]


def test_seasonal_forcing_by_season_maps_each_period_start() -> None:
    forcing = FlowWellForcingSeasonalConfig(
        by_season={"DJF": 1.0, "MAM": 2.0, "JJA": 3.0, "SON": 4.0},
    )

    values = resolve_period_values_from_forcing(
        forcing=forcing,
        simulation_window=_monthly_window(),
        nper=4,
        label="well forcing",
    )

    # Jan/Feb -> DJF, Mar/Apr -> MAM.
    assert values == [1.0, 1.0, 2.0, 2.0]
