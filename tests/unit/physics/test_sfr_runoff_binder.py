"""The catchment runoff routes through an active SFR network, never twice.

``apply_runoff_to_sfr_networks`` turns the catchment runoff data family
(internal unit mm/day) into the volumetric SFR ``runoff`` forcing
(rate x catchment area, m3/s). Precedence with the lake meteo binder: when an
active SFR network takes the runoff, the lake's legacy direct ``runoff * area``
feed is skipped (the water reaches a coupled lake through MVR); rainfall and
evaporation stay on the lake surface in every mode.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.structure_binders import (
    apply_lake_meteo_forcings_to_flow,
    apply_runoff_to_sfr_networks,
    sfr_routes_catchment_runoff,
)

_WINDOW_DATES = ["2000-01-01", "2000-01-02", "2000-01-03"]
# 86.4 mm/day = 1e-6 m/s; x 1 km2 = 1 m3/s.
_RUNOFF_MM_DAY = [86.4, 43.2, 0.0]
_AREA_M2 = 1.0e6


def _three_period_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2000-01-03"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _runoff_result() -> SimpleNamespace:
    record = PointRecord(
        station_id="_catchment",
        variable="runoff",
        source="sim2",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": pd.to_datetime(_WINDOW_DATES), "value": _RUNOFF_MM_DAY}),
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2000, 1, 3),
    )
    return SimpleNamespace(has_points=True, points=[record])


def _flow(*, with_sfr: bool, sfr_runoff: object = None) -> SimpleNamespace:
    active_bc = ["lake", "sfr", "drainage"] if with_sfr else ["lake", "drainage"]
    sfr_payload = {"outflow_to_lake": 1}
    if sfr_runoff is not None:
        sfr_payload["runoff"] = sfr_runoff
    return SimpleNamespace(
        active_bc=active_bc,
        sinks_sources={
            "lakes": {"lac0": {"bedleak": 0.1}},
            "sfr": {"net0": sfr_payload} if with_sfr else {},
        },
    )


def test_runoff_binder_attaches_a_volumetric_values_forcing() -> None:
    flow = _flow(with_sfr=True)
    attached = apply_runoff_to_sfr_networks(
        flow=flow,
        runoff=_runoff_result(),
        simulation_window=_three_period_window(),
        catchment_area_m2=_AREA_M2,
    )
    assert attached is True
    forcing = flow.sinks_sources["sfr"]["net0"]["runoff"]
    assert forcing["kind"] == "values"
    assert forcing["units"] == "m3/s"
    assert forcing["values"] == pytest.approx([1.0, 0.5, 0.0])


def test_runoff_binder_never_overrides_a_config_forcing() -> None:
    declared = {"kind": "constant", "value": 0.2, "units": "m3/s"}
    flow = _flow(with_sfr=True, sfr_runoff=declared)
    attached = apply_runoff_to_sfr_networks(
        flow=flow,
        runoff=_runoff_result(),
        simulation_window=_three_period_window(),
        catchment_area_m2=_AREA_M2,
    )
    assert attached is False
    assert flow.sinks_sources["sfr"]["net0"]["runoff"] is declared


def test_runoff_binder_is_a_noop_without_an_active_sfr() -> None:
    flow = _flow(with_sfr=False)
    attached = apply_runoff_to_sfr_networks(
        flow=flow,
        runoff=_runoff_result(),
        simulation_window=_three_period_window(),
        catchment_area_m2=_AREA_M2,
    )
    assert attached is False
    assert sfr_routes_catchment_runoff(flow) is False


def test_lake_meteo_binder_skips_runoff_when_sfr_routes_it() -> None:
    flow = _flow(with_sfr=True)
    assert sfr_routes_catchment_runoff(flow) is True
    attached = apply_lake_meteo_forcings_to_flow(
        flow=flow,
        runoff=_runoff_result(),
        simulation_window=_three_period_window(),
        catchment_area_m2=_AREA_M2,
    )
    # Nothing to attach: the only offered family is the runoff and SFR takes it.
    assert attached is False
    assert flow.sinks_sources["lakes"]["lac0"].get("runoff") is None


def test_lake_meteo_binder_keeps_runoff_without_sfr() -> None:
    flow = _flow(with_sfr=False)
    attached = apply_lake_meteo_forcings_to_flow(
        flow=flow,
        runoff=_runoff_result(),
        simulation_window=_three_period_window(),
        catchment_area_m2=_AREA_M2,
    )
    assert attached is True
    forcing = flow.sinks_sources["lakes"]["lac0"]["runoff"]
    assert forcing["values"] == pytest.approx([1.0, 0.5, 0.0])


def test_lake_keeps_rainfall_and_evaporation_with_an_active_sfr() -> None:
    # Rain on the lake surface is not runoff: it stays bound in every mode.
    rain = _runoff_result()
    flow = _flow(with_sfr=True)
    attached = apply_lake_meteo_forcings_to_flow(
        flow=flow,
        precipitation=rain,
        runoff=_runoff_result(),
        simulation_window=_three_period_window(),
        catchment_area_m2=_AREA_M2,
    )
    assert attached is True
    payload = flow.sinks_sources["lakes"]["lac0"]
    assert payload["rainfall"]["values"] == pytest.approx([1.0e-6, 0.5e-6, 0.0])
    assert payload.get("runoff") is None
