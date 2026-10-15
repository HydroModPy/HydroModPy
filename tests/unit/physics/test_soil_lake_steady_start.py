"""Soil + lake runs: steady start, weekly spin-up and lake runoff shares."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.time_forcing import compact_pre_resolved_forcings
from hydromodpy.physics.hydrology.soil_reservoir.config import (
    SoilReservoirConfig,
    spinup_refusal,
)


def test_compact_pre_resolved_forcings_averages_by_period_length() -> None:
    lakes = {
        "lake_a": {
            "bedleak": 0.1,
            "runoff": {"kind": "values", "values": [1.0, 3.0], "units": "m3/s"},
            "rainfall": {"kind": "constant", "value": 2.0},
        }
    }
    sfr = {"net": {"runoff": {"kind": "values", "values": [2.0, 4.0], "units": "m3/s"}}}
    sinks_sources = {"lakes": lakes, "sfr": sfr}

    count = compact_pre_resolved_forcings(sinks_sources, period_lengths=[1.0, 3.0])

    assert count == 2
    assert lakes["lake_a"]["runoff"]["values"] == [pytest.approx(2.5)]
    assert lakes["lake_a"]["runoff"]["units"] == "m3/s"
    assert lakes["lake_a"]["rainfall"] == {"kind": "constant", "value": 2.0}
    assert sfr["net"]["runoff"]["values"] == [pytest.approx(3.5)]


def test_compact_pre_resolved_forcings_leaves_other_lengths_alone() -> None:
    lakes = {"lake_a": {"runoff": {"kind": "values", "values": [1.0, 3.0, 5.0]}}}

    count = compact_pre_resolved_forcings({"lakes": lakes}, period_lengths=[1.0, 1.0])

    assert count == 0
    assert lakes["lake_a"]["runoff"]["values"] == [1.0, 3.0, 5.0]


def test_steady_ic_flow_copy_has_one_period_lake_forcings() -> None:
    from hydromodpy.solver.modflow6.support.steady_initial_conditions import (
        _compact_flow_forcings_to_one_period,
    )

    flow = SimpleNamespace(
        sinks_sources={
            "lakes": {"l": {"runoff": {"kind": "values", "values": [0.0] * 51 + [52.0]}}}
        }
    )
    model = SimpleNamespace(
        time_grid=SimpleNamespace(period_lengths_seconds=np.full(52, 7 * 86400.0))
    )

    _compact_flow_forcings_to_one_period(flow, model)

    assert flow.sinks_sources["lakes"]["l"]["runoff"]["values"] == [pytest.approx(1.0)]


def test_first_year_spinup_is_accepted_on_52_weekly_periods() -> None:
    config = SoilReservoirConfig(ru=100.0)

    assert spinup_refusal(config, 52 * 7) is None


_DATES = ["2000-01-01", "2000-01-02", "2000-01-03"]


def _window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2000-01-03"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _runoff(values_mm_day: list[float]) -> object:
    from hydromodpy.data.contracts.load_result import LoadResult

    rec = PointRecord(
        station_id="grid_mean",
        variable="climatic",
        source="custom",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": pd.to_datetime(_DATES), "value": values_mm_day}),
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2000, 1, 3),
    )
    return LoadResult(points=[rec])


def test_two_lakes_without_sfr_share_the_basin_runoff_once() -> None:
    from hydromodpy.physics.flow.structure_binders import apply_lake_meteo_forcings_to_flow

    flow = SimpleNamespace(sinks_sources={"lakes": {"a": {}, "b": {}}})
    apply_lake_meteo_forcings_to_flow(
        flow=flow,
        runoff=_runoff([1.0, 1.0, 1.0]),
        simulation_window=_window(),
        catchment_area_m2=1.0e7,
    )
    lakes = flow.sinks_sources["lakes"]
    total = lakes["a"]["runoff"]["values"][0] + lakes["b"]["runoff"]["values"][0]
    assert total == pytest.approx((1.0e-3 / 86400.0) * 1.0e7)


def test_lake_runoff_follows_its_contributing_area() -> None:
    from hydromodpy.physics.flow.structure_binders import apply_lake_meteo_forcings_to_flow

    flow = SimpleNamespace(sinks_sources={"lakes": {"a": {}, "b": {}}})
    apply_lake_meteo_forcings_to_flow(
        flow=flow,
        runoff=_runoff([1.0, 1.0, 1.0]),
        simulation_window=_window(),
        catchment_area_m2=1.0e7,
        lake_contributing_areas_m2={"a": 2.0e6, "b": 6.0e6},
    )
    rate = 1.0e-3 / 86400.0
    lakes = flow.sinks_sources["lakes"]
    assert lakes["a"]["runoff"]["values"][0] == pytest.approx(rate * 2.0e6)
    assert lakes["b"]["runoff"]["values"][0] == pytest.approx(rate * 6.0e6)
