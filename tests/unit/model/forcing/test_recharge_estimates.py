"""Recharge estimators of [recharge_estimates] (depths in mm, discharge in mm/day, heads in m).

Each estimator is checked on a closed form or on a limit it must reach, and on
the places where ESPERE's code departs from its method. The last tests run the
whole section on small loaded series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.forcing.recharge_estimates import (
    annual_totals,
    chapman_maxwell,
    daily_pieces,
    eckhardt,
    guttman_zuckerman,
    kessler,
    kessler_correction,
    recession_constant,
    turc,
    wallingford,
    wtf,
)
from hydromodpy.model.forcing.recharge_estimates_config import RechargeEstimatesConfig
from hydromodpy.model.forcing.recharge_estimates_run import estimate_lines, estimate_recharge


def test_turc_is_its_closed_form_with_the_cube_of_temperature():
    capacity = 300.0 + 25.0 * 11.0 + 0.05 * 11.0**3
    expected = 900.0 * (1.0 - 1.0 / np.sqrt(0.9 + (900.0 / capacity) ** 2))
    assert turc(np.array([900.0]), np.array([11.0]))[0] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("rain", "recharge"),
    [
        pytest.param(100.0, 0.0, id="below 180 mm gives no recharge"),
        pytest.param(599.0, 0.45 * (599.0 - 180.0), id="first line"),
        pytest.param(600.0, 0.88 * (600.0 - 410.0), id="600 starts the second"),
        pytest.param(1000.0, 0.97 * (1000.0 - 463.0), id="1000 belongs to the third"),
        pytest.param(1300.0, 0.97 * (1300.0 - 463.0), id="third line"),
    ],
)
def test_guttman_zuckerman_lines_and_thresholds(rain, recharge):
    assert guttman_zuckerman(np.array([rain]))[0] == pytest.approx(recharge)


@pytest.mark.parametrize(
    ("cpr", "step"),
    [
        (0.04, 0.0),
        (-0.30, -3.0),
        (0.59, 7.0),
        (0.69, 13.0),
        (0.705, 15.0),  # ESPERE falls back to 0 between 0.70 and 0.71
        (0.90, 15.0),
    ],
)
def test_kessler_steps_leave_no_gap(cpr, step):
    assert kessler_correction(cpr) == step


def test_kessler_skips_the_first_year_and_follows_its_polynomial():
    rain = np.array([800.0, 900.0, 700.0])
    spring = np.array([300.0, 330.0, 250.0])
    autumn = np.array([280.0, 280.0, 280.0])  # every autumn is the mean: no correction
    values = kessler(rain, spring, autumn)
    assert np.isnan(values[0])
    mu = 100.0 * 330.0 / 900.0
    rate = 0.0003 * mu**3 - 0.0339 * mu**2 + 2.2778 * mu - 1.5758
    assert values[1] == pytest.approx(rate * 900.0 / 100.0)


def test_chapman_maxwell_tends_to_half_the_discharge():
    assert chapman_maxwell(np.full(400, 10.0), 0.95)[-1] == pytest.approx(5.0, rel=1e-6)


@pytest.mark.parametrize("bfi_max", [0.25, 0.5, 0.8])
def test_eckhardt_tends_to_bfi_max_of_the_discharge(bfi_max):
    assert eckhardt(np.full(600, 10.0), 0.97, bfi_max)[-1] == pytest.approx(
        10.0 * bfi_max, rel=1e-6
    )


def storm_discharge(n_days: int = 730) -> np.ndarray:
    """A slow recession every 60 days, with a sharp storm peak on top of it."""
    t = np.arange(n_days)
    slow = 2.0 + 1.5 * np.cos(2 * np.pi * t / 365)
    quick = 12.0 * (0.6 ** (t % 60))
    return slow + quick


def test_wallingford_stays_under_the_discharge_between_its_turning_points():
    q = storm_discharge()
    baseflow = wallingford(q)
    inside = np.isfinite(baseflow)
    assert inside.sum() > 600
    assert np.all(baseflow[inside] <= q[inside] + 1e-12)
    assert 0.3 < baseflow[inside].sum() / q[inside].sum() < 0.95


def test_the_recession_constant_is_read_on_falling_days():
    t = np.arange(40)
    q = np.concatenate([10.0 * 0.95**t, 30.0 * 0.95**t])
    assert recession_constant(q) == pytest.approx(0.95, rel=1e-9)


def test_wtf_without_correction_sums_the_rises():
    head = np.array([10.0, 10.2, 10.1, 10.4, 10.3])
    np.testing.assert_allclose(wtf(head, 0.05, correction="none").sum(), 1000 * 0.05 * 0.5)


def test_wtf_adds_back_the_decline_the_rain_interrupted():
    floor = 10.0
    falling = floor + 2.0 * np.exp(-0.05 * np.arange(20))
    rise = np.linspace(falling[-1], falling[-1] + 0.5, 4)[1:]
    second = rise[-1] - 0.01 * np.arange(1, 12)
    head = np.concatenate([[falling[0] - 0.1], falling, rise, second])
    plain = wtf(head, 0.05, correction="none").sum()
    corrected = wtf(head, 0.05, correction="recession").sum()
    assert corrected > plain


def test_wtf_does_not_depend_on_the_datum():
    t = np.arange(60)
    head = 2.0 * np.exp(-0.05 * (t % 30)) + 0.3 * (t // 30)
    low = wtf(head, 0.05).sum()
    high = wtf(head + 450.0, 0.05).sum()
    assert low == pytest.approx(high)


def test_short_gaps_are_filled_and_long_ones_cut_the_series():
    index = pd.date_range("2020-01-01", periods=60, freq="D")
    series = pd.Series(np.arange(60.0), index=index)
    series.iloc[10:13] = np.nan  # 3 days: filled
    series.iloc[30:36] = np.nan  # 6 days: cut
    pieces = daily_pieces(series, 3)
    assert len(pieces) == 2
    assert pieces[0].iloc[11] == pytest.approx(11.0)
    assert pieces[1].index[0] == index[36]


def test_a_year_counts_only_when_covered_on_90_percent_of_its_days():
    index = pd.date_range("2019-01-01", "2020-12-31", freq="D")
    daily = pd.Series(1.0, index=index)
    daily = daily[~((daily.index.year == 2020) & (daily.index.month <= 3))]
    totals = annual_totals(daily)
    assert list(totals.index) == [2019]
    assert totals[2019] == pytest.approx(365.0)


def series_record(variable: str, index: pd.DatetimeIndex, values: np.ndarray, station="X1"):
    return PointRecord(
        station_id=station,
        variable=variable,
        source="test",
        unit="-",
        frequency="D",
        data=pd.DataFrame({"datetime": index, "value": values}),
        date_start=index[0].to_pydatetime(),
        date_end=index[-1].to_pydatetime(),
    )


def loaded_data():
    index = pd.date_range("2015-01-01", "2018-12-31", freq="D")
    t = np.arange(index.size)
    rng = np.random.default_rng(4)
    rain = rng.gamma(0.6, 6.0, index.size) * (rng.random(index.size) < 0.5)
    temperature = 11.0 + 7.0 * np.sin(2 * np.pi * (t - 110) / 365.25)
    discharge_mm = storm_discharge(index.size) * 0.3
    area_km2 = 50.0
    discharge_m3s = discharge_mm / 1000.0 * area_km2 * 1e6 / 86400.0
    head = 20.0 + np.cos(2 * np.pi * t / 365.25)
    run = (pd.Series(0.8, index=index), pd.Series(0.1, index=index))
    return dict(
        precipitation=LoadResult(points=[series_record("precipitation", index, rain)]),
        temperature=LoadResult(points=[series_record("temperature", index, temperature)]),
        hydrometry=LoadResult(points=[series_record("discharge", index, discharge_m3s)]),
        piezometry=LoadResult(points=[series_record("head", index, head, station="PZ1")]),
        area_km2=area_km2,
        run_water=run,
    )


def test_every_method_gives_its_rows_on_loaded_series():
    config = RechargeEstimatesConfig(wtf={"specific_yield": 0.05})
    rows, notes = estimate_recharge(config, **loaded_data())

    frame = pd.DataFrame(rows)
    assert notes == []
    for method in (
        "turc",
        "guttman_zuckerman",
        "kessler",
        "wallingford",
        "chapman_maxwell",
        "eckhardt",
        "wtf",
        "run",
    ):
        assert method in set(frame["method"]), method
    assert set(frame.loc[frame["method"] == "turc", "quantity"]) == {"effective_rainfall"}
    assert frame.loc[frame["method"] == "wtf", "station"].unique().tolist() == ["PZ1"]
    factor = frame.loc[frame["method"] == "closing_factor", "value"].iloc[0]
    gauge_mean = (storm_discharge(1461) * 0.3).mean()
    assert factor == pytest.approx(gauge_mean / 0.9, rel=1e-6)


def test_a_method_without_its_data_is_skipped_with_a_reason():
    data = loaded_data()
    data["hydrometry"] = None
    rows, notes = estimate_recharge(RechargeEstimatesConfig(methods=["eckhardt", "turc"]), **data)

    assert {row["method"] for row in rows} == {"turc", "run"}
    assert notes == ["eckhardt: no [data.hydrometry] loaded"]
    lines = estimate_lines(rows, notes)
    assert lines[-1] == "  skipped eckhardt: no [data.hydrometry] loaded"


def test_all_skips_wtf_without_a_specific_yield_and_a_list_requires_it():
    assert "wtf" not in RechargeEstimatesConfig().selected()
    assert "piezometry" not in RechargeEstimatesConfig().families()
    with pytest.raises(ValueError, match="needs the specific yield"):
        RechargeEstimatesConfig(methods=["wtf"])
    with pytest.raises(ValueError, match="write a list taken from"):
        RechargeEstimatesConfig(methods=["espere"])


def test_the_water_balance_rows_are_monthly_sums_of_covered_months():
    from hydromodpy.model.forcing.recharge_estimates_run import water_balance_rows

    index = pd.date_range("2016-01-01", "2017-12-31", freq="D")
    rain_minus_etr = pd.Series(2.0, index=index)
    gauge = pd.Series(1.0, index=index)
    gauge["2016-03-01":"2016-03-10"] = np.nan

    rows, notes = water_balance_rows(rain_minus_etr, gauge)

    frame = pd.DataFrame(rows)
    assert notes == []
    assert len(frame) == 2 * 23  # March 2016 lacks a third of its days
    january = frame[(frame["year"] == 2016) & (frame["month"] == 1)].set_index("quantity")["value"]
    assert january["rain_minus_etr"] == pytest.approx(62.0)
    assert january["gauged_discharge"] == pytest.approx(31.0)


def test_turc_has_no_value_where_its_capacity_is_not_positive():
    assert np.isnan(turc(np.array([500.0]), np.array([-12.0]))[0])


def test_wtf_does_not_extend_declines_that_grow():
    head = np.concatenate(
        [[9.0], 10.0 - 0.01 * np.arange(1, 10) ** 2, [10.5], 10.5 - 0.02 * np.arange(1, 8)]
    )
    np.testing.assert_allclose(
        wtf(head, 0.05, correction="recession").sum(), wtf(head, 0.05, correction="none").sum()
    )


def test_every_estimate_reads_the_years_of_the_run_only():
    data = loaded_data()
    config = RechargeEstimatesConfig(methods=["eckhardt", "guttman_zuckerman"])
    rows, _ = estimate_recharge(
        config, window=(pd.Timestamp("2016-01-01"), pd.Timestamp("2017-12-31")), **data
    )
    years = {row["year"] for row in rows if row["year"] is not None and row["method"] != "run"}
    assert years == {2016, 2017}
