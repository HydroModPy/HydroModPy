"""The steady recharge of ``[data.recharge] formula``, from the yearly weather (mm, mm/day)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.model.forcing.recharge_computed import computed_recharge
from hydromodpy.model.forcing.recharge_estimates import guttman_zuckerman, turc

WINDOW = (pd.Timestamp("2015-01-01"), pd.Timestamp("2017-12-31"))
DAYS = pd.date_range("2014-01-01", "2018-12-31", freq="D")


def grid(variable: str, daily: float) -> LoadResult:
    """A daily grid of two by two cells holding ``daily`` everywhere."""
    x = np.array([350000.0, 358000.0])
    y = np.array([6790000.0, 6782000.0])
    values = np.full((len(DAYS), y.size, x.size), daily)
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)}, coords={"time": DAYS.values, "y": y, "x": x}
    )
    record = FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day" if variable == "precipitation" else "degC",
        data=dataset,
        bbox=(350000.0, 6782000.0, 358000.0, 6790000.0),
        crs="EPSG:2154",
        date_start=DAYS[0],
        date_end=DAYS[-1],
    )
    return LoadResult(fields=[record])


def test_guttman_gives_its_yearly_value_as_one_daily_rate_over_the_window():
    steady = computed_recharge(grid("precipitation", 2.5), None, "guttman_zuckerman", WINDOW)

    rain = steady.yearly_mm.index.map(lambda y: 2.5 * (366 if y % 4 == 0 else 365))
    expected = guttman_zuckerman(np.asarray(rain, dtype=float))
    assert list(steady.yearly_mm.index) == [2015, 2016, 2017]
    assert steady.yearly_mm.to_numpy() == pytest.approx(expected)
    record = steady.load_result.fields[0]
    assert record.variable == "recharge"
    assert record.source == "guttman_zuckerman"
    values = record.data["recharge"].values
    assert values.shape == (1096, 2, 2)
    assert np.allclose(values, expected.mean() / 365.25)


def test_turc_reads_the_temperature_and_is_named_an_effective_rainfall():
    steady = computed_recharge(
        grid("precipitation", 2.5), grid("temperature", 11.0), "turc", WINDOW
    )

    rain = np.array([365.0, 366.0, 365.0]) * 2.5
    assert steady.yearly_mm.to_numpy() == pytest.approx(turc(rain, np.full(3, 11.0)))
    assert "an effective rainfall, taken whole as recharge" in steady.line()


def test_a_window_without_a_complete_year_is_refused():
    short = (pd.Timestamp("2015-03-01"), pd.Timestamp("2015-09-30"))
    with pytest.raises(DataContractViolation, match="Widen \\[simulation.time\\] to whole years"):
        computed_recharge(grid("precipitation", 2.5), None, "guttman_zuckerman", short)


def test_kessler_needs_the_year_before():
    one_year = (pd.Timestamp("2015-01-01"), pd.Timestamp("2015-12-31"))
    with pytest.raises(DataContractViolation, match="two consecutive complete years"):
        computed_recharge(grid("precipitation", 2.5), None, "kessler", one_year)


def test_station_precipitation_is_refused():
    with pytest.raises(DataContractViolation, match="holds no single daily grid"):
        computed_recharge(LoadResult(), None, "turc", WINDOW)
