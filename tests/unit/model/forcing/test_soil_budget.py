"""The gauged discharge of the printed soil budget is a depth in mm per year over the catchment.

A discharge in m3/s over an area in km2 is a depth per year, with 86 400 s per day,
365.25 days per year, 1e6 m2 per km2 and 1000 mm per m. The rows are worked by hand.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.forcing.soil_budget import gauged_discharge_line

_DAYS = pd.date_range("2015-01-01", periods=10, freq="D").values


def _station(discharge_m3_s: float) -> PointRecord:
    dates = pd.DatetimeIndex(_DAYS)
    return PointRecord(
        station_id="OUTLET",
        variable="discharge",
        source="test",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": np.full(len(dates), discharge_m3_s)}),
        date_start=dates[0],
        date_end=dates[-1],
    )


# One row per case: the discharge in m3/s, the area in km2 and the depth printed in mm/year.
# One m3/s over one km2 is 31 557 600 s * 1 m3/s / 1e6 m2 = 31.5576 m a year.
_DEPTHS = [
    pytest.param(1.0, 1.0, "31557.6", id="one_m3_s_on_one_km2"),
    pytest.param(0.001, 1.0, "31.6", id="one_liter_per_second_on_one_km2"),
    pytest.param(0.5, 100.0, "157.8", id="half_a_m3_s_on_a_hundred_km2"),
    pytest.param(2.0, 10.0, "6311.5", id="two_m3_s_on_ten_km2"),
    pytest.param(0.0, 10.0, "0.0", id="a_dry_river_reads_zero_and_not_minus_zero"),
]


@pytest.mark.parametrize(("discharge", "area_km2", "printed"), _DEPTHS)
def test_a_discharge_is_a_depth_per_year_over_the_catchment(discharge, area_km2, printed) -> None:
    line = gauged_discharge_line(
        LoadResult(points=[_station(discharge)]), days=_DAYS, catchment_area_km2=area_km2
    )

    assert f": {printed} mm/year on 10 of 10 days" in line
    assert f"catchment {area_km2:.2f} km2" in line
