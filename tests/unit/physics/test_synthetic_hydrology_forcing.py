"""Unit tests for synthetic hydrological forcing helpers."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from hydromodpy.physics.hydrology.synthetic.forcing import (
    build_hydrological_step_series,
    build_hydrological_year_dates,
    build_recharge_from_reservoir_chronicle,
    enforce_annual_precipitation_total,
    generate_daily_precipitation,
    make_piecewise_constant_daily_qin,
    precipitation_to_inflow,
)


def test_generate_daily_precipitation_is_reproducible_and_non_negative() -> None:
    first = generate_daily_precipitation(n_days=30, seed=123)
    second = generate_daily_precipitation(n_days=30, seed=123)

    assert np.array_equal(first, second)
    assert first.shape == (30,)
    assert np.all(first >= 0.0)
    assert np.any(first > 0.0)


def test_enforce_annual_precipitation_total_rescales_without_changing_shape() -> None:
    precip = np.asarray([1.0, 2.0, 3.0])

    scaled = enforce_annual_precipitation_total(precip, target_annual_mm=60.0)

    assert scaled.tolist() == pytest.approx([10.0, 20.0, 30.0])
    with pytest.raises(ValueError, match="cannot be empty"):
        enforce_annual_precipitation_total(np.asarray([]))
    with pytest.raises(ValueError, match="non-positive total"):
        enforce_annual_precipitation_total(np.zeros(3))


def test_precipitation_to_inflow_applies_monthly_losses_and_runoff_coefficient() -> None:
    precip = np.asarray([5.0, 5.0, 1.0])
    dates = np.asarray([date(2020, 4, 1), date(2020, 10, 1), date(2020, 5, 1)])

    peff, qin = precipitation_to_inflow(
        precip,
        dates,
        runoff_coeff=0.2,
        losses_mm_day=2.0,
        losses_months=(4, 5),
    )

    assert peff.tolist() == pytest.approx([3.0, 5.0, 0.0])
    assert qin.tolist() == pytest.approx([0.6, 1.0, 0.0])
    with pytest.raises(ValueError, match="same length"):
        precipitation_to_inflow(precip, dates[:2])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        precipitation_to_inflow(precip, dates, runoff_coeff=1.5)


def test_hydrological_year_dates_and_step_series_follow_month_masks() -> None:
    dates = build_hydrological_year_dates(n_days=4, start_year=2020)

    assert dates.tolist() == [
        date(2020, 10, 1),
        date(2020, 10, 2),
        date(2020, 10, 3),
        date(2020, 10, 4),
    ]
    series = build_hydrological_step_series(
        dates,
        wet_months=(10,),
        wet_value=3.0,
        dry_value=1.0,
    )
    assert series.tolist() == [3.0, 3.0, 3.0, 3.0]
    with pytest.raises(ValueError, match="dates cannot be empty"):
        build_hydrological_step_series(np.asarray([], dtype=object))
    with pytest.raises(ValueError, match=r"\[1, 12\]"):
        build_hydrological_step_series(dates, wet_months=(13,))


def test_build_recharge_from_reservoir_chronicle_returns_consistent_arrays() -> None:
    result = build_recharge_from_reservoir_chronicle(
        n_days=20,
        start_year=2021,
        target_annual_precip_mm=100.0,
        precip_seed=4,
        runoff_coeff=0.25,
        losses_mm_day=1.0,
        scale_to_m_per_day=1.0e-3,
    )

    assert set(result) == {
        "dates",
        "precip_mm_day",
        "peff_mm_day",
        "qin_mm_day",
        "recharge_m_per_day",
    }
    assert result["dates"].shape == (20,)
    assert float(np.sum(result["precip_mm_day"])) == pytest.approx(100.0)
    assert result["recharge_m_per_day"].tolist() == pytest.approx(
        (result["qin_mm_day"] * 1.0e-3).tolist()
    )


def test_piecewise_constant_qin_clamps_time_to_available_days() -> None:
    qin = make_piecewise_constant_daily_qin(np.asarray([1.0, 2.0, 3.0]))

    assert qin(-5.0) == 1.0
    assert qin(0.9) == 1.0
    assert qin(1.0) == 2.0
    assert qin(99.0) == 3.0
    with pytest.raises(ValueError, match="cannot be empty"):
        make_piecewise_constant_daily_qin(np.asarray([]))
