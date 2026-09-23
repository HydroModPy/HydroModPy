"""A synthetic recharge sample is stamped at the start of the period it stands for."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.variables.recharge.config import RechargeSourceConfig
from hydromodpy.data.variables.recharge.synthetic import generate
from hydromodpy.physics.forcing.time_alignment import (
    align_forcing_series_to_simulation_window,
)


def _series(config: RechargeSourceConfig, **kwargs) -> pd.Series:
    (record,) = generate(config, **kwargs)
    return record.data.set_index("datetime")["value"]


def _annual_source() -> RechargeSourceConfig:
    return RechargeSourceConfig(
        source="synthetic",
        values=[0.6023],
        freq="YE",
        start_date="2020-01-01",
        periods=1,
    )


@pytest.mark.parametrize(
    "project_period",
    [None, (datetime(2020, 1, 1), datetime(2020, 12, 31))],
)
def test_an_annual_value_is_stamped_on_the_first_day_of_its_year(project_period):
    series = _series(_annual_source(), project_period=project_period)
    assert list(series.index) == [pd.Timestamp("2020-01-01")]


def test_month_end_samples_are_stamped_on_their_month_start():
    config = RechargeSourceConfig(
        source="synthetic",
        values=[1.0, 2.0, 3.0],
        freq="ME",
        start_date="2020-01-01",
        periods=3,
    )
    series = _series(config)
    assert list(series.index) == list(pd.date_range("2020-01-01", periods=3, freq="MS"))
    assert list(series) == [1.0, 2.0, 3.0]


def test_start_anchored_and_daily_frequencies_keep_their_stamps():
    config = RechargeSourceConfig(
        source="synthetic", values=[1.0], freq="MS", start_date="2020-01-01", periods=2
    )
    assert list(_series(config).index) == [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")]
    daily = RechargeSourceConfig(source="synthetic", values=[1.0], start_date="2020-01-01")
    assert list(_series(daily).index) == [pd.Timestamp("2020-01-01")]


def test_an_annual_value_covers_every_month_of_a_monthly_window():
    # The 06_vire_selune steady project: one 'YE' value, default monthly window.
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2020-01-01"),
        end=pd.Timestamp("2020-12-31"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )
    series = _series(
        _annual_source(),
        project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)),
    )
    aligned = align_forcing_series_to_simulation_window(
        series, simulation_window=window, label="recharge"
    )
    assert len(aligned) == 12
    assert aligned.tolist() == pytest.approx([0.6023] * 12)
