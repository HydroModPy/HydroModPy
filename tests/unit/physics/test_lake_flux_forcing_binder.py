"""File-loaded lake inflow / withdrawal feed the LAK forcings.

The lake_inflow / lake_withdrawal data families load one PointRecord per lake.
``apply_lake_flux_forcings_to_flow`` aggregates each series to the simulation
stress periods and attaches it as a pre-resolved ``values`` forcing on the lake
payload, which the LAK builder then expands per period. A forcing already
declared in config is never overridden by the data file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.structure_binders import apply_lake_flux_forcings_to_flow
from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow6.builders.lake import build_lake_period_data

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
    from hydromodpy.physics.flow.structure_binders import apply_lake_meteo_forcings_to_flow

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
    from hydromodpy.physics.flow.structure_binders import apply_lake_meteo_forcings_to_flow

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
