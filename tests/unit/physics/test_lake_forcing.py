from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import TypeAdapter, ValidationError

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.base.forcing import SurfaceRateForcing, VolumeRateForcing
from hydromodpy.physics.flow.binders.lakes import (
    apply_lake_flux_forcings_to_flow,
    apply_lake_meteo_forcings_to_flow,
)
from hydromodpy.physics.flow.binders.streams import (
    apply_runoff_to_sfr_networks,
    sfr_routes_catchment_runoff,
)
from hydromodpy.physics.flow.sinks_sources.wells import FlowWellConfig
from hydromodpy.physics.flow.time_forcing import (
    compact_pre_resolved_forcings,
    resolve_period_values_from_forcing,
)
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig, spinup_refusal
from hydromodpy.solver.modflow6.builders._lake_outlets import _forcing_si_per_period
from hydromodpy.solver.modflow6.builders.lake import build_lake_period_data

# Lake and SFR rainfall and evaporation are rates in length per time.
#
# MODFLOW 6 reads them as L/T. They used to share the well forcing, whose value
# is a volume per time, so '2 mm/day' was refused and a unit could be applied
# twice.


TWO_MM_PER_DAY = 2.0e-3 / 86400.0


RATE = TypeAdapter(SurfaceRateForcing)


VOLUME = TypeAdapter(VolumeRateForcing)


def test_a_volume_per_time_is_refused_as_a_rate() -> None:
    with pytest.raises(ValidationError, match="not a rate per unit of surface"):
        RATE.validate_python(
            {"kind": "seasonal", "units": "m3/s", "by_month": dict.fromkeys(range(1, 13), 1.0)}
        )
    with pytest.raises(ValidationError, match="Cannot convert"):
        RATE.validate_python({"kind": "constant", "value": "2 m**3/s"})


def test_a_unit_written_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="Write the unit once"):
        RATE.validate_python({"kind": "constant", "value": "2 mm/day", "units": "mm/day"})


def test_piecewise_segments_give_their_unit_to_the_forcing() -> None:
    forcing = RATE.validate_python(
        {
            "kind": "piecewise",
            "segments": [
                {
                    "start": "2020-01-01",
                    "forcing": {"kind": "constant", "value": 2.0, "units": "mm/day"},
                }
            ],
        }
    )
    assert forcing.units == "mm/day"
    with pytest.raises(ValidationError, match="Write units once"):
        RATE.validate_python(
            {
                "kind": "piecewise",
                "units": "m/s",
                "segments": [
                    {
                        "start": "2020-01-01",
                        "forcing": {"kind": "constant", "value": 2.0, "units": "mm/day"},
                    }
                ],
            }
        )


def test_a_well_value_with_its_unit_is_not_scaled_by_the_well_units_again() -> None:
    with pytest.raises(ValidationError, match="Write the unit once"):
        FlowWellConfig(
            location={"kind": "cell", "cell": [0, 1, 1]},
            units="m3/day",
            forcing={"kind": "constant", "value": "100 m**3/day"},
        )
    well = FlowWellConfig(
        location={"kind": "cell", "cell": [0, 1, 1]},
        forcing={"kind": "constant", "value": "86.4 m**3/day"},
    )
    assert well.forcing.units == "m3/s"
    assert well.forcing.value == pytest.approx(1.0e-3)


def test_lake_runoff_inflow_and_withdrawal_stay_volumes_per_time() -> None:
    forcing = VOLUME.validate_python({"kind": "constant", "value": 0.01, "units": "m3/s"})
    model = SimpleNamespace(nper=1, time_grid=None)
    assert _forcing_si_per_period(
        model, forcing, volumetric=True, label="withdrawal", nper=1
    ) == pytest.approx((0.01,))


# File-loaded lake inflow / withdrawal feed the LAK forcings.
#
# The lake_inflow / lake_withdrawal data families load one PointRecord per lake.
# ``apply_lake_flux_forcings_to_flow`` aggregates each series to the simulation
# stress periods and attaches it as a pre-resolved ``values`` forcing on the lake
# payload, which the LAK builder then expands per period. A forcing already
# declared in config is never overridden by the data file.


# A 3-day span (end inclusive + one trailing period) resolves to 3 stress periods.
_WINDOW_DATES = ["2000-01-01", "2000-01-02", "2000-01-03"]


def _three_period_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2000-01-03"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _inflow_result(values: list[float]) -> SimpleNamespace:
    record = PointRecord(
        station_id="lac0",
        variable="lake_inflow",
        source="custom",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": pd.to_datetime(_WINDOW_DATES), "value": values}),
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2000, 1, 3),
    )
    return SimpleNamespace(points=[record])


def test_flux_binder_attaches_a_values_forcing() -> None:
    flow = SimpleNamespace(sinks_sources={"lakes": {"lac0": {"bedleak": 0.1}}})
    attached = apply_lake_flux_forcings_to_flow(
        flow=flow,
        lake_inflow=_inflow_result([5.0, 9.0, 13.0]),
        simulation_window=_three_period_window(),
    )
    assert attached is True
    forcing = flow.sinks_sources["lakes"]["lac0"]["inflow"]
    assert forcing["kind"] == "values"
    assert forcing["units"] == "m3/s"
    assert forcing["values"] == pytest.approx([5.0, 9.0, 13.0])


def test_flux_binder_does_not_override_a_config_forcing() -> None:
    # A forcing declared in config wins; the data file is the alternative source.
    declared = {"kind": "constant", "value": 1.0, "units": "m3/s"}
    flow = SimpleNamespace(sinks_sources={"lakes": {"lac0": {"bedleak": 0.1, "inflow": declared}}})
    attached = apply_lake_flux_forcings_to_flow(
        flow=flow,
        lake_inflow=_inflow_result([5.0, 9.0, 13.0]),
        simulation_window=_three_period_window(),
    )
    assert attached is False
    assert flow.sinks_sources["lakes"]["lac0"]["inflow"] is declared


def test_values_forcing_resolves_to_per_period_values() -> None:
    forcing = {"kind": "values", "values": [5.0, 9.0], "units": "m3/s"}
    resolved = resolve_period_values_from_forcing(
        forcing=forcing, simulation_window=None, nper=2, label="lake.inflow"
    )
    assert resolved == pytest.approx([5.0, 9.0])
    with pytest.raises(ValueError, match="does not match nper"):
        resolve_period_values_from_forcing(
            forcing=forcing, simulation_window=None, nper=3, label="lake.inflow"
        )


@dataclass
class _Proc:
    lak_forcing_mode: str = "auto"
    ts6_min_periods: int = 120


@dataclass
class _Cfg:
    process_specific: _Proc = None  # type: ignore[assignment]


class _Model:
    def __init__(self, window: ResolvedSimulationTimeWindow) -> None:
        self.time_grid = SimpleNamespace(window=window)
        self.nper = 3
        self.perlen = [86400.0, 86400.0, 86400.0]
        self.modflow_config = _Cfg(process_specific=_Proc())


def test_builder_expands_a_file_loaded_values_forcing_inline() -> None:
    model = _Model(_three_period_window())
    lakes = {"lac0": {"inflow": {"kind": "values", "values": [5.0, 9.0, 13.0], "units": "m3/s"}}}
    rows, ts_series = build_lake_period_data(model, lakes=lakes)
    assert ts_series == []
    # Below the TS6 threshold, the file-loaded series expands inline per period.
    assert set(rows) == {0, 1, 2}
    assert rows[0] == [[0, "inflow", pytest.approx(5.0)]]
    assert rows[1] == [[0, "inflow", pytest.approx(9.0)]]
    assert rows[2] == [[0, "inflow", pytest.approx(13.0)]]


def _meteo_result(values_mm_day: list[float]) -> object:
    from hydromodpy.data.contracts.load_result import LoadResult

    rec = PointRecord(
        station_id="grid_mean",
        variable="climatic",
        source="custom",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": pd.to_datetime(_WINDOW_DATES), "value": values_mm_day}),
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2000, 1, 3),
    )
    return LoadResult(points=[rec])


def test_meteo_binder_attaches_sim2_derived_rate_and_volumetric_forcings() -> None:
    from hydromodpy.physics.flow.binders.lakes import apply_lake_meteo_forcings_to_flow

    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir_cheze": {"bedleak": 0.1}}})
    attached = apply_lake_meteo_forcings_to_flow(
        flow=flow,
        precipitation=_meteo_result([4.0, 4.0, 4.0]),  # mm/day
        etp=_meteo_result([2.0, 2.0, 2.0]),
        runoff=_meteo_result([1.0, 1.0, 1.0]),
        simulation_window=_three_period_window(),
        catchment_area_m2=1.0e7,  # 10 km2
    )
    assert attached is True
    p = flow.sinks_sources["lakes"]["reservoir_cheze"]
    # rainfall / evaporation are rates (m/s): mm/day -> m/s.
    assert p["rainfall"]["units"] == "m/s"
    assert p["rainfall"]["values"][0] == pytest.approx(4.0e-3 / 86400.0)
    assert p["evaporation"]["values"][0] == pytest.approx(2.0e-3 / 86400.0)
    # runoff is volumetric (m3/s) = catchment runoff rate (m/s) * area (m2).
    assert p["runoff"]["units"] == "m3/s"
    assert p["runoff"]["values"][0] == pytest.approx((1.0e-3 / 86400.0) * 1.0e7)


def test_meteo_binder_does_not_override_a_config_forcing() -> None:
    from hydromodpy.physics.flow.binders.lakes import apply_lake_meteo_forcings_to_flow

    declared = {"kind": "constant", "value": 0.001, "units": "m/day"}
    flow = SimpleNamespace(
        sinks_sources={"lakes": {"reservoir_cheze": {"bedleak": 0.1, "rainfall": declared}}}
    )
    apply_lake_meteo_forcings_to_flow(
        flow=flow,
        precipitation=_meteo_result([4.0, 4.0, 4.0]),
        simulation_window=_three_period_window(),
    )
    assert flow.sinks_sources["lakes"]["reservoir_cheze"]["rainfall"] is declared


# The catchment runoff routes through an active SFR network, never twice.
#
# ``apply_runoff_to_sfr_networks`` turns the catchment runoff data family
# (internal unit mm/day) into the volumetric SFR ``runoff`` forcing
# (rate x catchment area, m3/s). Precedence with the lake meteo binder: when an
# active SFR network takes the runoff, the lake's legacy direct ``runoff * area``
# feed is skipped (the water reaches a coupled lake through MVR); rainfall and
# evaporation stay on the lake surface in every mode.


# 86.4 mm/day = 1e-6 m/s; x 1 km2 = 1 m3/s.
_RUNOFF_MM_DAY = [86.4, 43.2, 0.0]


_AREA_M2 = 1.0e6


def _runoff_result() -> SimpleNamespace:
    record = PointRecord(
        station_id="R001",
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
    from hydromodpy.physics.flow.binders.lakes import apply_lake_meteo_forcings_to_flow

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
    from hydromodpy.physics.flow.binders.lakes import apply_lake_meteo_forcings_to_flow

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
