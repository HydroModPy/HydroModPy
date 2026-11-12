"""Synthetic recharge series (m/s) built from a list of values and an optional sine wave.

Each value is stamped on the start of its step. A wave is the mean of a sine of
the given period over each step, so it shrinks by sin(x) / x with x = pi L / P
for a step of length L.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.variables.recharge.config import RechargeSourceConfig
from hydromodpy.data.variables.recharge.synthetic import generate
from hydromodpy.model.forcing.time_alignment import align_forcing_series_to_simulation_window

pytestmark = pytest.mark.fast

TWO_YEARS = (datetime(2003, 1, 1), datetime(2004, 12, 31))


def stamped_series(**fields) -> pd.Series:
    (record,) = generate(RechargeSourceConfig(source="synthetic", **fields))
    return record.data.set_index("datetime")["value"]


def wave_values(freq: str, **wave: float) -> np.ndarray:
    config = RechargeSourceConfig(source="synthetic", values=[2.0], freq=freq, **wave)
    return generate(config, project_period=TWO_YEARS)[0].data["value"].to_numpy()


def test_month_end_samples_are_stamped_on_their_month_start():
    series = stamped_series(values=[1.0, 2.0, 3.0], freq="ME", start_date="2020-01-01", periods=3)

    assert list(series.index) == list(pd.date_range("2020-01-01", periods=3, freq="MS"))
    assert list(series) == [1.0, 2.0, 3.0]


STAMPS = [
    pytest.param(
        {"freq": "MS", "periods": 2},
        [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")],
        id="month start",
    ),
    pytest.param({}, [pd.Timestamp("2020-01-01")], id="daily"),
]


@pytest.mark.parametrize(("fields", "stamps"), STAMPS)
def test_start_anchored_and_daily_frequencies_keep_their_stamps(fields, stamps):
    series = stamped_series(values=[1.0], start_date="2020-01-01", **fields)

    assert list(series.index) == stamps


def test_an_annual_value_covers_every_month_of_a_monthly_window():
    # The steady project of example 06: one 'YE' value, default monthly window.
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2020-01-01"),
        end=pd.Timestamp("2020-12-31"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )
    config = RechargeSourceConfig(
        source="synthetic", values=[0.6023], freq="YE", start_date="2020-01-01", periods=1
    )
    (record,) = generate(config, project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)))

    aligned = align_forcing_series_to_simulation_window(
        record.data.set_index("datetime")["value"], simulation_window=window, label="recharge"
    )

    assert len(aligned) == 12
    assert aligned.tolist() == pytest.approx([0.6023] * 12)


@pytest.mark.parametrize(
    ("freq", "tolerance"), [("D", 0.001), ("MS", 0.05), ("ME", 0.05), ("QS", 0.4)]
)
def test_the_wave_keeps_its_period_and_brings_no_net_water(freq: str, tolerance: float) -> None:
    values = wave_values(freq, amplitude=1.0, period_days=365)

    assert values.max() == pytest.approx(3.0, abs=tolerance)
    assert values.min() == pytest.approx(1.0, abs=tolerance)
    # Two whole waves, within the day that 2004 adds to 730 days.
    config = RechargeSourceConfig(source="synthetic", values=[2.0], freq=freq)
    stamps = generate(config, project_period=TWO_YEARS)[0].data["datetime"]
    days = stamps.diff().dt.days.shift(-1).fillna(stamps.diff().dt.days.iloc[-1]).to_numpy()
    assert np.average(values, weights=days) == pytest.approx(2.0, abs=0.01)


def test_a_daily_sample_holds_the_mean_of_the_wave_over_its_day() -> None:
    values = wave_values("D", amplitude=1.0, period_days=4)
    omega = 2.0 * np.pi / 4.0

    assert values[0] - 2.0 == pytest.approx((1.0 - np.cos(omega)) / omega)


def test_offset_adds_to_the_wave() -> None:
    plain = wave_values("D", amplitude=1.0, period_days=365)
    shifted = wave_values("D", amplitude=1.0, period_days=365, offset=0.5)

    assert shifted - plain == pytest.approx(np.full(plain.size, 0.5))


@pytest.mark.parametrize("values", [[1.0, 2.0], [1.0] * 800])
def test_a_list_of_the_wrong_length_is_refused(values: list[float]) -> None:
    config = RechargeSourceConfig(source="synthetic", values=values, freq="MS")

    with pytest.raises(ValueError, match=f"holds {len(values)} numbers"):
        generate(config, project_period=TWO_YEARS)
