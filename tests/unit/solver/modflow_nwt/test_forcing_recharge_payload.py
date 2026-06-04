"""
Tests for RCH/EVT payload building via FlowToModflowAdapter._build_recharge_payload.

These tests exercise the logic that was previously in ForcingToModflowAdapter,
now merged into FlowToModflowAdapter (see flow.sinks_sources.recharge).
"""

from __future__ import annotations

import types
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter

from ._test_forcing_adapter_builders import _build_solver_mesh


def _make_adapter(
    recharge_cfg,
    flow_regime,
    nper,
    active_sinks_sources=None,
    *,
    simulation_window=None,
):
    """Build a minimal FlowToModflowAdapter focused on the recharge path."""
    if active_sinks_sources is None:
        active_sinks_sources = ["recharge"]
    flow = types.SimpleNamespace(
        sinks_sources={"recharge": recharge_cfg},
        flow_regime=flow_regime,
        active_sinks_sources=active_sinks_sources,
        config=None,
    )
    return FlowToModflowAdapter(
        flow=flow,
        domain=None,
        solver_mesh=_build_solver_mesh(),
        nper=nper,
        simulation_window=simulation_window,
        sink_fill=False,
    )


def _make_point_recharge_record(
    *,
    station_id: str,
    x: float,
    y: float,
    january_value_mm_day: float,
    february_value_mm_day: float | None = None,
) -> PointRecord:
    dates = pd.date_range("2003-01-01", "2003-02-28", freq="D")
    values = np.full(len(dates), float(january_value_mm_day), dtype=float)
    if february_value_mm_day is not None:
        values[dates.month == 2] = float(february_value_mm_day)
    return PointRecord(
        station_id=station_id,
        variable="recharge",
        source="test",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": values}),
        date_start=datetime(2003, 1, 1),
        date_end=datetime(2003, 2, 28),
        location=StationLocation(id=station_id, x=x, y=y, crs="EPSG:2154"),
    )


def test_recharge_steady_mapping_returns_mean_scalar():
    cfg = FlowRechargeConfig(values={0: 0.2, 1: 0.4}, units="m/s")
    adapter = _make_adapter(cfg, "steady", nper=2)

    rch_data = adapter._build_recharge_payload()

    assert rch_data == pytest.approx(0.3)


def test_recharge_transient_mapping_returned_as_dict():
    cfg = FlowRechargeConfig(values={0: 0.1, 1: 0.2}, units="m/s")
    adapter = _make_adapter(cfg, "transient", nper=2)

    rch_data = adapter._build_recharge_payload()

    assert rch_data == {0: 0.1, 1: 0.2}


def test_recharge_series_coverage_error_rejects_missing_window_data():
    recharge = pd.Series(
        [0.1],
        index=pd.DatetimeIndex([pd.Timestamp("2003-01-01")]),
        dtype=float,
    )
    cfg = FlowRechargeConfig(values=recharge, units="m/s")
    adapter = _make_adapter(
        cfg,
        "transient",
        nper=2,
        simulation_window=ResolvedSimulationTimeWindow(
            start=pd.Timestamp("2003-01-01"),
            end=pd.Timestamp("2003-02-28"),
            step_value=1,
            step_unit="month",
            coverage_policy="error",
        ),
    )

    with pytest.raises(ValueError, match="does not fully cover simulation window"):
        adapter._build_recharge_payload()


def test_recharge_scalar_broadcast_to_all_periods():
    cfg = FlowRechargeConfig(values=0.001, units="mm/day")
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data = adapter._build_recharge_payload()

    assert all(rch_data[k] == pytest.approx(1.0e-6 / 86400.0) for k in range(3))


def test_negative_recharge_routes_to_evt_and_clips_rch():
    cfg = FlowRechargeConfig(
        values=[0.1, -0.2, 0.3],
        first_clim="first",
        units="m/s",
        negative_to_evt=True,
    )
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data = adapter._build_recharge_payload()
    evt_spd, _, _ = adapter._build_etp_payload()

    assert rch_data[0] == pytest.approx(0.1)
    assert rch_data[1] == pytest.approx(0.0)
    assert rch_data[2] == pytest.approx(0.3)
    assert evt_spd is not None
    assert evt_spd[0] == pytest.approx(0.0)
    assert evt_spd[1] == pytest.approx(0.2)
    assert evt_spd[2] == pytest.approx(0.0)


def test_recharge_point_source_builds_period_arrays():
    point = _make_point_recharge_record(
        station_id="R1",
        x=0.5,
        y=0.5,
        january_value_mm_day=8.0,
        february_value_mm_day=4.0,
    )
    cfg = FlowRechargeConfig(
        values=0.0,
        first_clim="first",
        heterogeneous_source=LoadResult(points=[point]),
        interpolation_method="nearest",
    )
    adapter = _make_adapter(
        cfg,
        "transient",
        nper=2,
        simulation_window=ResolvedSimulationTimeWindow(
            start=pd.Timestamp("2003-01-01"),
            end=pd.Timestamp("2003-02-28"),
            step_value=1,
            step_unit="month",
            coverage_policy="error",
        ),
    )

    rch_data = adapter._build_recharge_payload()

    assert set(rch_data.keys()) == {0, 1}
    np.testing.assert_allclose(
        rch_data[0],
        np.full((1, 1), 8.0e-3 / 86400.0, dtype=float),
    )
    np.testing.assert_allclose(
        rch_data[1],
        np.full((1, 1), 4.0e-3 / 86400.0, dtype=float),
    )


def test_recharge_none_gives_none_payload():
    adapter = _make_adapter(None, "transient", nper=2)

    rch_data = adapter._build_recharge_payload()

    assert rch_data is None


def test_recharge_first_clim_first_uses_index_zero():
    recharge = pd.Series([0.5, 0.3, 0.1], dtype=float)
    cfg = FlowRechargeConfig(values=recharge, first_clim="first", units="m/s")
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data = adapter._build_recharge_payload()

    assert rch_data[0] == pytest.approx(0.5)


def test_recharge_first_clim_numeric_scalar():
    recharge = pd.Series([0.5, 0.3, 0.1], dtype=float)
    cfg = FlowRechargeConfig(values=recharge, first_clim=0.0, units="m/s")
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data = adapter._build_recharge_payload()

    assert rch_data[0] == pytest.approx(0.0)


def test_recharge_rejects_invalid_flow_regime():
    cfg = FlowRechargeConfig(values=0.001)
    adapter = _make_adapter(cfg, "invalid_regime", nper=1)

    with pytest.raises(ValueError, match="flow.flow_regime must be"):
        adapter._build_recharge_payload()


# ---------------------------------------------------------------------------
# active_sinks_sources gate tests (recharge)
# ---------------------------------------------------------------------------


def test_recharge_not_activated_returns_none():
    """When 'recharge' is absent from active_sinks_sources, payload is None."""
    cfg = FlowRechargeConfig(values=0.001)
    adapter = _make_adapter(cfg, "transient", nper=3, active_sinks_sources=[])

    rch_data = adapter._build_recharge_payload()

    assert rch_data is None


def test_recharge_not_activated_ignores_configured_values():
    """Even with a non-zero config, inactive recharge returns None."""
    cfg = FlowRechargeConfig(values=pd.Series([0.1, 0.2, 0.3], dtype=float))
    adapter = _make_adapter(cfg, "transient", nper=3, active_sinks_sources=["wells"])

    rch_data = adapter._build_recharge_payload()

    assert rch_data is None
