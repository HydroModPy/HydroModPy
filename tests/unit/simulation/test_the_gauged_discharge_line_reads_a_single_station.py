"""The gauged-discharge line always says something: a value, or why not.

``gauged_discharge_line`` compares the soil's recharge to the outlet's
measured discharge only when exactly one station is loaded, on a window with
a known catchment area and at least one value inside it; otherwise it names
the reason.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.data.contracts import LoadResult, PointRecord
from hydromodpy.simulation.soil_recharge import gauged_discharge_line

_DAYS = pd.date_range("2015-01-01", periods=10, freq="D").values
_AREA_KM2 = 10.0


def _station(*, station_id="OUTLET", values=None, dates=None) -> PointRecord:
    dates = pd.DatetimeIndex(_DAYS) if dates is None else dates
    values = np.full(len(dates), 1.0) if values is None else values
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": values}),
        date_start=dates[0],
        date_end=dates[-1],
    )


def test_no_hydrometry_says_so() -> None:
    line = gauged_discharge_line(None, days=_DAYS, catchment_area_km2=_AREA_KM2)
    assert line == "gauged discharge: not shown, no [data.hydrometry] loaded"


def test_an_empty_load_result_says_so() -> None:
    line = gauged_discharge_line(LoadResult(), days=_DAYS, catchment_area_km2=_AREA_KM2)
    assert line == "gauged discharge: not shown, no [data.hydrometry] loaded"


def test_two_stations_say_the_outlet_is_ambiguous() -> None:
    hydrometry = LoadResult(points=[_station(station_id="A"), _station(station_id="B")])
    line = gauged_discharge_line(hydrometry, days=_DAYS, catchment_area_km2=_AREA_KM2)
    assert line == (
        "gauged discharge: not shown, 2 stations loaded and the comparison needs "
        "the one at the outlet"
    )


def test_an_unknown_catchment_area_says_so() -> None:
    hydrometry = LoadResult(points=[_station()])
    line = gauged_discharge_line(hydrometry, days=_DAYS, catchment_area_km2=None)
    assert line == "gauged discharge: not shown, the catchment area is unknown"


def test_a_station_empty_on_the_window_says_so() -> None:
    other_days = pd.date_range("2020-01-01", periods=10, freq="D")
    hydrometry = LoadResult(points=[_station(dates=other_days)])
    line = gauged_discharge_line(hydrometry, days=_DAYS, catchment_area_km2=_AREA_KM2)
    assert line == (
        "gauged discharge: not shown, the station has no value between 2015-01-01 and 2015-01-10"
    )


def test_a_single_station_reads_the_conversion_formula() -> None:
    mean_q_m3s = 0.669
    hydrometry = LoadResult(points=[_station(station_id="NANCON", values=np.full(10, mean_q_m3s))])

    line = gauged_discharge_line(hydrometry, days=_DAYS, catchment_area_km2=64.62)

    expected_v = mean_q_m3s * 86400 * 365.25 / (64.62 * 1e6) * 1000
    assert line == (
        f"gauged discharge NANCON: {expected_v:.1f} mm/year on 10 of 10 days, catchment 64.62 km2"
    )
