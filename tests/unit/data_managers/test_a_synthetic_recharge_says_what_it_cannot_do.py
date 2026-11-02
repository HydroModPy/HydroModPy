"""The synthetic recharge keeps its wave on any step, and refuses what it would ignore.

The sinusoid counted its time in samples, so a monthly series with
``period_days = 365`` went from 2.02 to 2.19 mm/day where 1 to 3 was asked. An
``offset`` alone and a list of the wrong length were dropped or repeated silently.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.recharge.config import RechargeSourceConfig
from hydromodpy.data.variables.recharge.synthetic import generate

pytestmark = pytest.mark.fast

TWO_YEARS = (datetime(2003, 1, 1), datetime(2004, 12, 31))


def _series(freq: str, **wave: float) -> np.ndarray:
    config = RechargeSourceConfig(source="synthetic", values=[2.0], freq=freq, **wave)
    return generate(config, project_period=TWO_YEARS)[0].data["value"].to_numpy()


@pytest.mark.parametrize(
    ("freq", "tolerance"), [("D", 0.001), ("MS", 0.05), ("ME", 0.05), ("QS", 0.4)]
)
def test_the_wave_keeps_its_period_and_brings_no_net_water(freq: str, tolerance: float) -> None:
    values = _series(freq, amplitude=1.0, period_days=365)

    # A mean over a step of length L shrinks the wave by sin(x) / x, with x = pi L / P.
    assert values.max() == pytest.approx(3.0, abs=tolerance)
    assert values.min() == pytest.approx(1.0, abs=tolerance)
    # Two whole waves, within the day that 2004 adds to 730 days.
    config = RechargeSourceConfig(source="synthetic", values=[2.0], freq=freq)
    stamps = generate(config, project_period=TWO_YEARS)[0].data["datetime"]
    days = stamps.diff().dt.days.shift(-1).fillna(stamps.diff().dt.days.iloc[-1]).to_numpy()
    assert np.average(values, weights=days) == pytest.approx(2.0, abs=0.01)


def test_a_daily_sample_holds_the_mean_of_the_wave_over_its_day() -> None:
    values = _series("D", amplitude=1.0, period_days=4)
    omega = 2.0 * np.pi / 4.0

    assert values[0] - 2.0 == pytest.approx((1.0 - np.cos(omega)) / omega)


def test_offset_adds_to_the_wave() -> None:
    plain = _series("D", amplitude=1.0, period_days=365)
    shifted = _series("D", amplitude=1.0, period_days=365, offset=0.5)

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
