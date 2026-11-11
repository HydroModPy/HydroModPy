"""A forcing series is converted once, from the unit of its data to the unit of the solver.

A rate loaded in mm/day reaches the solver in m/s, so a value is divided by
1000 mm/m and by 86 400 s/day. The rows give the value in each unit, worked by hand.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.forcing.forcing_bridge import (
    build_forcing_series,
    extract_homogeneous_series,
    scaled_load_result,
)

_MM_DAY_TO_M_S = 1.0 / (1000.0 * 86400.0)
_DAYS = pd.date_range("2020-01-01", periods=3, freq="D")


def _station(values, *, station_id="A") -> PointRecord:
    return PointRecord(
        station_id=station_id,
        variable="recharge",
        source="test",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": _DAYS, "value": values}),
        date_start=_DAYS[0],
        date_end=_DAYS[-1],
    )


# One row per rate: its value in mm/day, and the value in m/s worked by hand.
_RATES = [
    pytest.param(86.4, 1.0e-6, id="86_mm_a_day_is_1e-6_m_s"),
    pytest.param(1.0, 1.0 / 86_400_000.0, id="one_mm_a_day"),
    pytest.param(0.0, 0.0, id="no_recharge"),
    pytest.param(-8.64, -1.0e-7, id="a_loss_keeps_its_sign"),
    pytest.param(864.0, 1.0e-5, id="a_flood_day"),
]


@pytest.mark.parametrize(("mm_per_day", "m_per_s"), _RATES)
def test_a_rate_in_mm_per_day_reaches_the_solver_in_m_per_second(mm_per_day, m_per_s) -> None:
    result = LoadResult(points=[_station([mm_per_day] * 3)])

    series = build_forcing_series(result, unit_conversion_factor=_MM_DAY_TO_M_S, label="recharge")

    assert series is not None
    np.testing.assert_allclose(series.to_numpy(), [m_per_s] * 3, rtol=1e-12, atol=0.0)


def test_a_factor_of_one_moves_no_number() -> None:
    result = LoadResult(points=[_station([0.1, 0.2, 0.3])])

    series = build_forcing_series(result)

    assert series.tolist() == [0.1, 0.2, 0.3]


def test_stations_are_averaged_in_the_data_unit_before_the_conversion() -> None:
    result = LoadResult(
        points=[_station([86.4] * 3, station_id="A"), _station([172.8] * 3, station_id="B")]
    )

    series = extract_homogeneous_series(result)
    converted = build_forcing_series(result, unit_conversion_factor=_MM_DAY_TO_M_S)

    np.testing.assert_allclose(series.to_numpy(), [129.6] * 3, rtol=1e-12)
    np.testing.assert_allclose(converted.to_numpy(), [1.5e-6] * 3, rtol=1e-12)


def test_a_scaled_load_result_multiplies_every_value_and_leaves_the_source_alone() -> None:
    result = LoadResult(points=[_station([1.0, 2.0, 3.0])])

    scaled = scaled_load_result(result, 10.0)

    assert scaled.points[0].data["value"].tolist() == [10.0, 20.0, 30.0]
    assert result.points[0].data["value"].tolist() == [1.0, 2.0, 3.0]
    assert scaled_load_result(result, 1.0) is result
