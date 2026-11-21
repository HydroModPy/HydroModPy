"""The recharge scenario of Abherve (2022): the mean year, with dry years put in a row."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.forcing.recharge_scenario import (
    RechargeScenarioConfig,
    recharge_scenario,
    scenario_values,
)

STAMPS = pd.date_range("1974-01-01", "1979-12-01", freq="MS")


def monthly(values_by_year: dict[int, float]) -> np.ndarray:
    """A monthly series, the same value in every month of a year, (T, 1)."""
    return np.array([values_by_year[s.year] for s in STAMPS], dtype=float)[:, None]


def test_the_normal_scenario_is_the_mean_year_repeated():
    values = monthly({1974: 1.0, 1975: 2.0, 1976: 3.0, 1977: 4.0, 1978: 5.0, 1979: 6.0})
    out = scenario_values(values, STAMPS, RechargeScenarioConfig())
    np.testing.assert_allclose(out, 3.5)


def test_dry_years_are_the_mean_of_the_chosen_years_month_by_month():
    values = monthly({1974: 2.0, 1975: 0.5, 1976: 0.3, 1977: 2.0, 1978: 2.0, 1979: 2.0})
    config = RechargeScenarioConfig(dry_years=[1975, 1976], repeat=2, start=1977)

    out = scenario_values(values, STAMPS, config)[:, 0]

    years = STAMPS.year
    np.testing.assert_allclose(out[(years == 1977) | (years == 1978)], 0.4)
    normal = values.mean()
    np.testing.assert_allclose(out[years == 1974], normal)
    np.testing.assert_allclose(out[years == 1979], normal)


def test_a_station_series_gets_its_scenario_too():
    frame = pd.DataFrame({"datetime": STAMPS, "value": np.arange(STAMPS.size, dtype=float)})
    record = PointRecord(
        station_id="s",
        variable="recharge",
        source="sim2",
        unit="mm/day",
        frequency="MS",
        data=frame,
        date_start=STAMPS[0].to_pydatetime(),
        date_end=STAMPS[-1].to_pydatetime(),
    )
    out = recharge_scenario(LoadResult(points=[record]), RechargeScenarioConfig())
    january = out.points[0].data["value"].to_numpy()[STAMPS.month == 1]
    np.testing.assert_allclose(january, np.mean(np.arange(STAMPS.size)[STAMPS.month == 1]))


@pytest.mark.parametrize(
    ("config", "message"),
    [
        pytest.param(
            dict(dry_years=[1950], repeat=2, start=1977), "does not cover", id="dry years outside"
        ),
        pytest.param(
            dict(dry_years=[1975], repeat=2, start=1990),
            "start the dry years inside",
            id="start outside",
        ),
    ],
)
def test_a_scenario_outside_the_loaded_years_is_refused(config, message):
    values = monthly({y: 1.0 for y in range(1974, 1980)})
    with pytest.raises(DataContractViolation, match=message):
        scenario_values(values, STAMPS, RechargeScenarioConfig(**config))


def test_dry_years_repeat_and_start_go_together():
    with pytest.raises(ValueError, match="go together"):
        RechargeScenarioConfig(dry_years=[1975], repeat=2)


def test_a_record_shorter_than_a_year_is_refused():
    stamps = pd.date_range("2000-01-01", periods=6, freq="MS")
    with pytest.raises(DataContractViolation, match="covers 6 of the 12 months"):
        scenario_values(np.ones((6, 1)), stamps, RechargeScenarioConfig())
