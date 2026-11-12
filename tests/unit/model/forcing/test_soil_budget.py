"""Printed soil budget block, in mm per year over the catchment.

A discharge in m3/s over an area in km2 is a depth per year, with 86 400 s per day,
365.25 days per year, 1e6 m2 per km2 and 1000 mm per m. The rows are worked by hand.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.forcing.soil_budget import (
    _no_negative_zero,
    gauged_discharge_line,
    soil_budget_lines,
)
from hydromodpy.model.forcing.soil_columns import SoilColumns
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.forcing.soil_forcing import SoilForcings
from hydromodpy.model.soil.kernel import SoilParameters, full_soil, run_soil_balance

DAYS = pd.date_range("2015-01-01", periods=10, freq="D").values
AREA_KM2 = 10.0


def station(station_id="OUTLET", values=1.0, dates=None) -> PointRecord:
    dates = pd.DatetimeIndex(DAYS) if dates is None else dates
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="test",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": np.full(len(dates), values)}),
        date_start=dates[0],
        date_end=dates[-1],
    )


# One row per case: the discharge in m3/s, the area in km2 and the depth printed in mm/year.
# One m3/s over one km2 is 31 557 600 s * 1 m3/s / 1e6 m2 = 31.5576 m a year.
DEPTHS = [
    pytest.param(1.0, 1.0, "31557.6", id="one m3/s on one km2"),
    pytest.param(0.001, 1.0, "31.6", id="one liter per second on one km2"),
    pytest.param(0.5, 100.0, "157.8", id="half a m3/s on a hundred km2"),
    pytest.param(2.0, 10.0, "6311.5", id="two m3/s on ten km2"),
    pytest.param(0.0, 10.0, "0.0", id="dry river reads zero, not minus zero"),
]


@pytest.mark.parametrize(("discharge", "area_km2", "printed"), DEPTHS)
def test_discharge_depth(discharge, area_km2, printed):
    line = gauged_discharge_line(
        LoadResult(points=[station(values=discharge)]), days=DAYS, catchment_area_km2=area_km2
    )

    assert f": {printed} mm/year on 10 of 10 days" in line
    assert f"catchment {area_km2:.2f} km2" in line


NO_HYDROMETRY = "gauged discharge: not shown, no [data.hydrometry] loaded"
OTHER_DAYS = pd.date_range("2020-01-01", periods=10, freq="D")

# The line always says something: a value, or why there is none.
NOT_SHOWN = [
    pytest.param(None, AREA_KM2, NO_HYDROMETRY, id="no hydrometry"),
    pytest.param(LoadResult(), AREA_KM2, NO_HYDROMETRY, id="empty load result"),
    pytest.param(
        LoadResult(points=[station("A"), station("B")]),
        AREA_KM2,
        "gauged discharge: not shown, 2 stations loaded and the comparison needs the one at the outlet",
        id="two stations",
    ),
    pytest.param(
        LoadResult(points=[station()]),
        None,
        "gauged discharge: not shown, the catchment area is unknown",
        id="unknown area",
    ),
    pytest.param(
        LoadResult(points=[station(dates=OTHER_DAYS)]),
        AREA_KM2,
        "gauged discharge: not shown, the station has no value between 2015-01-01 and 2015-01-10",
        id="station empty on the window",
    ),
]


@pytest.mark.parametrize(("hydrometry", "area_km2", "line"), NOT_SHOWN)
def test_gauged_line_gives_the_reason(hydrometry, area_km2, line):
    assert gauged_discharge_line(hydrometry, days=DAYS, catchment_area_km2=area_km2) == line


def test_single_station_reads_the_conversion_formula():
    mean_q_m3s = 0.669
    hydrometry = LoadResult(points=[station("NANCON", mean_q_m3s)])

    line = gauged_discharge_line(hydrometry, days=DAYS, catchment_area_km2=64.62)

    expected_mm = mean_q_m3s * 86400 * 365.25 / (64.62 * 1e6) * 1000
    assert line == (
        f"gauged discharge NANCON: {expected_mm:.1f} mm/year on 10 of 10 days, catchment 64.62 km2"
    )


def steady_year_forcings() -> SoilForcings:
    # One cell, one year, steady climate: the recharge is reached on day one and held.
    days = pd.date_range("2015-01-01", "2015-12-31", freq="D")
    precipitation = np.full((len(days), 1), 10.0)
    etp = np.full((len(days), 1), 2.0)
    params = SoilParameters(
        ru_mm=np.array([50.0]),
        alpha=1.0,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )
    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
    columns = SoilColumns(
        cell_index=np.array([0]),
        class_index=np.array([0]),
        x=np.array([0.0]),
        y=np.array([0.0]),
        ru_shape=np.array([1.0]),
        cell_fraction=np.array([1.0]),
        basin_weight=np.array([1.0]),
    )
    return SoilForcings(
        recharge=None,
        residual_etp=None,
        runoff=None,
        days=days.values,
        precipitation=precipitation,
        etp=etp,
        fluxes=fluxes,
        columns=columns,
        config=SoilReservoirConfig(ru=50.0, alpha=1.0, kc=1.0, spinup="none"),
        parameters=params,
        spinup_cycles=0,
        never_full_columns=0,
        crs="EPSG:2154",
    )


def test_block_lines():
    lines = soil_budget_lines(
        steady_year_forcings(),
        ladder=((50.0, 2920.0), (100.0, 2500.0)),
        gauged_line="gauged discharge TEST: 300.0 mm/year on 365 of 365 days, catchment 10.00 km2",
        sent_to_evt=True,
    )

    assert lines[2] == 'starting soil: full (spinup = "none")'
    assert lines[9] == f"{'storage change':<22}{0.0:>+8.1f}{0.0:>+18.1f}{0.0:>+17.1f}"


def test_unmet_etp_names_the_missing_activation():
    lines = soil_budget_lines(
        steady_year_forcings(), ladder=(), gauged_line=NO_HYDROMETRY, sent_to_evt=False
    )

    unmet_line = next(line for line in lines if line.startswith("unmet ETP"))
    assert unmet_line == (
        'unmet ETP 0.0 mm/year, not sent to MODFLOW: add "etp" to '
        "[flow.sinks_sources.etp] to let a shallow water table evaporate it"
    )


def test_value_rounding_to_zero_has_no_minus_sign():
    assert f"{_no_negative_zero(-1e-16, 1):.1f}" == "0.0"
    assert f"{_no_negative_zero(-0.04, 1):.1f}" == "0.0"
    assert f"{_no_negative_zero(-0.05, 1):.1f}" == "-0.1"
