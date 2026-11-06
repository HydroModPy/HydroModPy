"""The recharge variable: config, synthetic stamps and what a synthetic series cannot do."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.variables.recharge.config import RechargeSourceConfig
from hydromodpy.data.variables.recharge.synthetic import generate
from hydromodpy.physics.forcing.time_alignment import (
    align_forcing_series_to_simulation_window,
)


@pytest.mark.fast
class TestRechargeSourceConfigValidation:
    @pytest.mark.parametrize(
        ("source", "match"),
        [
            ("custom", "path"),
            ("synthetic", "values"),
        ],
        ids=["custom_requires_path", "synthetic_requires_values"],
    )
    def test_requires_field(self, source, match):
        with pytest.raises(ValueError, match=match):
            RechargeSourceConfig(source=source)

    def test_custom_with_path_ok(self, tmp_path):
        cfg = RechargeSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"
        assert cfg.path == tmp_path

    def test_custom_with_source_unit_ok(self, tmp_path):
        cfg = RechargeSourceConfig(source="custom", path=tmp_path, source_unit="m/day")
        assert cfg.source_unit == "m/day"

    def test_sim2_without_path_ok(self):
        cfg = RechargeSourceConfig(source="sim2")
        assert cfg.source == "sim2"
        assert cfg.path is None

    def test_synthetic_with_values_ok(self):
        cfg = RechargeSourceConfig(source="synthetic", values=[1.5, 2.0])
        assert cfg.source == "synthetic"
        assert cfg.values == [1.5, 2.0]

    def test_synthetic_with_amplitude(self):
        """Amplitude and period_days drive the seasonal synthetic recharge signal."""
        cfg = RechargeSourceConfig(
            source="synthetic",
            values=[1.0],
            amplitude=0.5,
            period_days=365,
        )
        assert cfg.amplitude == 0.5
        assert cfg.period_days == 365

    def test_invalid_source_rejected(self):
        with pytest.raises(Exception):
            RechargeSourceConfig(source="unknown_provider")

    def test_literal_sources(self):
        """The allowed sources are exactly custom, sim2, synthetic."""
        # Verify each valid source is accepted (sim2 needs no extras,
        # custom needs path, synthetic needs values).
        RechargeSourceConfig(source="sim2")
        RechargeSourceConfig(source="custom", path=Path("/tmp"))
        RechargeSourceConfig(source="synthetic", values=[1.0])

        # Anything else is rejected
        for bad in ("nasa", "ERA5", ""):
            with pytest.raises(Exception):
                RechargeSourceConfig(source=bad)


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


pytestmark = pytest.mark.fast


TWO_YEARS = (datetime(2003, 1, 1), datetime(2004, 12, 31))


def _wave_series(freq: str, **wave: float) -> np.ndarray:
    config = RechargeSourceConfig(source="synthetic", values=[2.0], freq=freq, **wave)
    return generate(config, project_period=TWO_YEARS)[0].data["value"].to_numpy()


@pytest.mark.parametrize(
    ("freq", "tolerance"), [("D", 0.001), ("MS", 0.05), ("ME", 0.05), ("QS", 0.4)]
)
def test_the_wave_keeps_its_period_and_brings_no_net_water(freq: str, tolerance: float) -> None:
    values = _wave_series(freq, amplitude=1.0, period_days=365)

    # A mean over a step of length L shrinks the wave by sin(x) / x, with x = pi L / P.
    assert values.max() == pytest.approx(3.0, abs=tolerance)
    assert values.min() == pytest.approx(1.0, abs=tolerance)
    # Two whole waves, within the day that 2004 adds to 730 days.
    config = RechargeSourceConfig(source="synthetic", values=[2.0], freq=freq)
    stamps = generate(config, project_period=TWO_YEARS)[0].data["datetime"]
    days = stamps.diff().dt.days.shift(-1).fillna(stamps.diff().dt.days.iloc[-1]).to_numpy()
    assert np.average(values, weights=days) == pytest.approx(2.0, abs=0.01)


def test_a_daily_sample_holds_the_mean_of_the_wave_over_its_day() -> None:
    values = _wave_series("D", amplitude=1.0, period_days=4)
    omega = 2.0 * np.pi / 4.0

    assert values[0] - 2.0 == pytest.approx((1.0 - np.cos(omega)) / omega)


def test_offset_adds_to_the_wave() -> None:
    plain = _wave_series("D", amplitude=1.0, period_days=365)
    shifted = _wave_series("D", amplitude=1.0, period_days=365, offset=0.5)

    assert shifted - plain == pytest.approx(np.full(plain.size, 0.5))


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"offset": 0.5}, "shifts the sinusoid"),
        ({"amplitude": 1.0}, "only with period_days"),
        ({"period_days": 365}, "only with amplitude"),
        ({"amplitude": 1.0, "period_days": 0}, "must be positive"),
    ],
)
def test_a_wave_half_written_is_refused(fields: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        RechargeSourceConfig(source="synthetic", values=[2.0], **fields)


def test_a_wave_on_a_loaded_source_is_refused() -> None:
    with pytest.raises(ValidationError, match="only shape a synthetic source"):
        RechargeSourceConfig(source="sim2", amplitude=1.0, period_days=365)


@pytest.mark.parametrize("values", [[1.0, 2.0], [1.0] * 800])
def test_a_list_of_the_wrong_length_is_refused(values: list[float]) -> None:
    config = RechargeSourceConfig(source="synthetic", values=values, freq="MS")

    with pytest.raises(ValueError, match=f"holds {len(values)} numbers"):
        generate(config, project_period=TWO_YEARS)


def test_runoff_ratio_is_gone() -> None:
    with pytest.raises(ValidationError, match="runoff_ratio"):
        RechargeSourceConfig(source="synthetic", values=[2.0], runoff_ratio=0.5)
