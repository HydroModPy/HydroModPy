"""
Tests for RCH/EVT payload building via FlowToModflowAdapter._build_recharge_payload.

These tests exercise the logic that was previously in ForcingToModflowAdapter,
now merged into FlowToModflowAdapter (see flow.sinks_sources.recharge).
"""
from __future__ import annotations

import types

import numpy as np
import pandas as pd
import pytest

from hydromodpy.process.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig, FlowWellConfig
from hydromodpy.solver.modflow_common.grid_context import GridReference
from hydromodpy.solver.modflow_nwt.modflow.flow_to_modflow_adapter import FlowToModflowAdapter


def _make_adapter(recharge_cfg, flow_regime, nper, active_sinks_sources=None):
    """Build a minimal FlowToModflowAdapter focused on the recharge path."""
    if active_sinks_sources is None:
        active_sinks_sources = ["recharge"]
    flow = types.SimpleNamespace(
        sinks_sources={"recharge": recharge_cfg},
        flow_regime=flow_regime,
        active_sinks_sources=active_sinks_sources,
        config=None,
    )
    dem = np.zeros((1, 1))
    return FlowToModflowAdapter(
        flow=flow,
        domain=None,
        sgrid=None,
        dem=dem,
        bottom_layer=dem,
        nlay=1,
        nrow=1,
        ncol=1,
        nper=nper,
        resolution=1.0,
        sink_fill=False,
    )


def test_recharge_builds_evt_and_clips_negative_values():
    recharge = pd.Series([0.1, -0.2, 0.3], dtype=float)
    cfg = FlowRechargeConfig(values=recharge, first_clim="mean", negative_to_evt=True)
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data, evt_spd = adapter._build_recharge_payload()

    assert evt_spd is not None
    assert evt_spd[0] == 0
    assert evt_spd[1] == pytest.approx(0.2)
    assert evt_spd[2] == pytest.approx(0.0)

    assert isinstance(rch_data, dict)
    assert rch_data[0] == pytest.approx(np.mean([0.1, 0.0, 0.3]))
    assert rch_data[1] == pytest.approx(0.0)
    assert rch_data[2] == pytest.approx(0.3)


def test_recharge_no_evt_when_negative_to_evt_false():
    recharge = pd.Series([0.1, -0.2, 0.3], dtype=float)
    cfg = FlowRechargeConfig(values=recharge, first_clim="mean", negative_to_evt=False)
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data, evt_spd = adapter._build_recharge_payload()

    assert evt_spd is None


def test_recharge_list_builds_evt_and_clips_negative_values():
    cfg = FlowRechargeConfig(values=[0.1, -0.2, 0.3], first_clim="mean", negative_to_evt=True)
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data, evt_spd = adapter._build_recharge_payload()

    assert evt_spd is not None
    assert evt_spd[0] == 0
    assert evt_spd[1] == pytest.approx(0.2)
    assert evt_spd[2] == pytest.approx(0.0)

    assert isinstance(rch_data, dict)
    assert rch_data[0] == pytest.approx(np.mean([0.1, 0.0, 0.3]))
    assert rch_data[1] == pytest.approx(0.0)
    assert rch_data[2] == pytest.approx(0.3)


def test_recharge_steady_mapping_returns_mean_scalar():
    cfg = FlowRechargeConfig(values={0: 0.2, 1: 0.4})
    adapter = _make_adapter(cfg, "steady", nper=2)

    rch_data, evt_spd = adapter._build_recharge_payload()

    assert evt_spd is None
    assert rch_data == pytest.approx(0.3)


def test_recharge_transient_mapping_returned_as_dict():
    cfg = FlowRechargeConfig(values={0: 0.1, 1: 0.2})
    adapter = _make_adapter(cfg, "transient", nper=2)

    rch_data, evt_spd = adapter._build_recharge_payload()

    assert evt_spd is None
    assert rch_data == {0: 0.1, 1: 0.2}


def test_recharge_scalar_broadcast_to_all_periods():
    cfg = FlowRechargeConfig(values=0.001)
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data, evt_spd = adapter._build_recharge_payload()

    assert evt_spd is None
    assert all(rch_data[k] == pytest.approx(0.001) for k in range(3))


def test_recharge_none_gives_none_payload():
    adapter = _make_adapter(None, "transient", nper=2)

    rch_data, evt_spd = adapter._build_recharge_payload()

    assert rch_data is None
    assert evt_spd is None


def test_recharge_first_clim_first_uses_index_zero():
    recharge = pd.Series([0.5, 0.3, 0.1], dtype=float)
    cfg = FlowRechargeConfig(values=recharge, first_clim="first")
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data, _ = adapter._build_recharge_payload()

    assert rch_data[0] == pytest.approx(0.5)


def test_recharge_first_clim_numeric_scalar():
    recharge = pd.Series([0.5, 0.3, 0.1], dtype=float)
    cfg = FlowRechargeConfig(values=recharge, first_clim=0.0)
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data, _ = adapter._build_recharge_payload()

    assert rch_data[0] == pytest.approx(0.0)


def test_recharge_rejects_invalid_flow_regime():
    cfg = FlowRechargeConfig(values=0.001)
    adapter = _make_adapter(cfg, "invalid_regime", nper=1)

    with pytest.raises(ValueError, match="flow.flow_regime must be"):
        adapter._build_recharge_payload()


# ---------------------------------------------------------------------------
# active_sinks_sources gate tests
# ---------------------------------------------------------------------------

def test_recharge_not_activated_returns_none():
    """When 'recharge' is absent from active_sinks_sources, both payloads are None."""
    cfg = FlowRechargeConfig(values=0.001)
    adapter = _make_adapter(cfg, "transient", nper=3, active_sinks_sources=[])

    rch_data, evt_spd = adapter._build_recharge_payload()

    assert rch_data is None
    assert evt_spd is None


def test_recharge_not_activated_ignores_configured_values():
    """Even with a non-zero config, inactive recharge returns None."""
    cfg = FlowRechargeConfig(values=pd.Series([0.1, 0.2, 0.3], dtype=float))
    adapter = _make_adapter(cfg, "transient", nper=3, active_sinks_sources=["wells"])

    rch_data, evt_spd = adapter._build_recharge_payload()

    assert rch_data is None
    assert evt_spd is None


def test_wells_not_activated_returns_empty_spd():
    """When 'wells' is absent from active_sinks_sources, WEL payload is empty."""

    flow = types.SimpleNamespace(
        sinks_sources={
            "recharge": None,
            "wells": {"W1": FlowWellConfig(cell=(0, 0, 0), flux=-1e-4)},
        },
        flow_regime="transient",
        active_sinks_sources=["recharge"],
        config=None,
    )
    dem = np.zeros((1, 1))
    adapter = FlowToModflowAdapter(
        flow=flow,
        domain=None,
        sgrid=None,
        dem=dem,
        bottom_layer=dem,
        nlay=1,
        nrow=1,
        ncol=1,
        nper=2,
        resolution=1.0,
        sink_fill=False,
    )

    wel_spd = adapter._build_well_stress_period_data()

    assert wel_spd == {}


def test_well_absolute_xy_is_resolved_to_solver_cell():
    flow = types.SimpleNamespace(
        sinks_sources={
            "recharge": None,
            "wells": {
                "W1": FlowWellConfig(
                    location_mode="absolute_xy",
                    layer=1,
                    x=125.0,
                    y=365.0,
                    flux=-1e-4,
                )
            },
        },
        flow_regime="transient",
        active_sinks_sources=["wells"],
        config=None,
    )
    dem = np.zeros((4, 5))
    adapter = FlowToModflowAdapter(
        flow=flow,
        domain=None,
        sgrid=None,
        dem=dem,
        bottom_layer=dem,
        nlay=2,
        nrow=4,
        ncol=5,
        nper=2,
        grid=GridReference(nrow=4, ncol=5, dx=50.0, dy=100.0, xmin=0.0, ymin=0.0, crs=None),
        resolution=1.0,
        sink_fill=False,
    )

    wel_spd = adapter._build_well_stress_period_data()

    assert wel_spd[0] == [[1, 0, 2, pytest.approx(-1e-4)]]
    assert wel_spd[1] == [[1, 0, 2, pytest.approx(-1e-4)]]


def test_well_relative_xy_is_resolved_to_solver_cell():
    flow = types.SimpleNamespace(
        sinks_sources={
            "recharge": None,
            "wells": {
                "W1": FlowWellConfig(
                    location_mode="relative_xy",
                    layer=0,
                    x_rel=0.4,
                    y_rel=0.25,
                    flux=[-1e-4, -2e-4],
                )
            },
        },
        flow_regime="transient",
        active_sinks_sources=["wells"],
        config=None,
    )
    dem = np.zeros((4, 5))
    adapter = FlowToModflowAdapter(
        flow=flow,
        domain=None,
        sgrid=None,
        dem=dem,
        bottom_layer=dem,
        nlay=1,
        nrow=4,
        ncol=5,
        nper=2,
        grid=GridReference(nrow=4, ncol=5, dx=10.0, dy=10.0, xmin=100.0, ymin=200.0, crs=None),
        resolution=1.0,
        sink_fill=False,
    )

    wel_spd = adapter._build_well_stress_period_data()

    assert wel_spd[0] == [[0, 3, 2, pytest.approx(-1e-4)]]
    assert wel_spd[1] == [[0, 3, 2, pytest.approx(-2e-4)]]


def test_well_relative_xy_defaults_to_layer_zero():
    well = FlowWellConfig(location_mode="relative_xy", x_rel=0.5, y_rel=0.5, flux=-1e-4)
    assert well.layer == 0


def test_well_forcing_constant_is_resolved_in_adapter_without_runtime_binding():
    flow = types.SimpleNamespace(
        sinks_sources={
            "recharge": None,
            "wells": {
                "W1": FlowWellConfig(
                    cell=(0, 0, 0),
                    units="m3/day",
                    forcing={"mode": "constant", "value": -86400.0},
                )
            },
        },
        flow_regime="transient",
        active_sinks_sources=["wells"],
        config=None,
    )
    dem = np.zeros((1, 1))
    adapter = FlowToModflowAdapter(
        flow=flow,
        domain=None,
        sgrid=None,
        dem=dem,
        bottom_layer=dem,
        nlay=1,
        nrow=1,
        ncol=1,
        nper=2,
        resolution=1.0,
        sink_fill=False,
    )

    wel_spd = adapter._build_well_stress_period_data()

    assert wel_spd[0] == [[0, 0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, 0, pytest.approx(-1.0)]]


# ---------------------------------------------------------------------------
# active_bc gate tests
# ---------------------------------------------------------------------------

def _make_bc_adapter(boundary_conditions, active_bc, nper=1, simulation_window=None):
    """Build a minimal FlowToModflowAdapter focused on the BC path."""
    dem = np.zeros((3, 3))
    flow = types.SimpleNamespace(
        boundary_conditions=boundary_conditions,
        initial_conditions=types.SimpleNamespace(
            h=types.SimpleNamespace(type="custom", value=0.0)
        ),
        flow_regime="transient",
        active_sinks_sources=[],
        active_bc=active_bc,
        sinks_sources={},
        config=None,
    )
    return FlowToModflowAdapter(
        flow=flow,
        domain=None,
        sgrid=None,
        dem=dem,
        bottom_layer=dem,
        nlay=1,
        nrow=3,
        ncol=3,
        nper=nper,
        simulation_window=simulation_window,
        resolution=1.0,
        sink_fill=False,
    )


def test_ocean_not_activated_returns_none_chd():
    """When 'ocean' is absent from active_bc, _build_ocean_chd returns None."""
    from unittest.mock import MagicMock
    ibound = np.ones((1, 3, 3))
    strt = np.zeros((1, 3, 3))
    drain_array = np.ones((3, 3))

    ocean_bc = MagicMock()
    ocean_bc.value = 0.0
    adapter = _make_bc_adapter({"ocean": ocean_bc}, active_bc=[])

    result = adapter._build_ocean_chd(ibound=ibound, strt=strt, drain_array=drain_array)

    assert result is None
    # ibound must not have been mutated by the ocean gate
    assert np.all(ibound == 1)


def test_drainage_not_activated_returns_none_drn():
    """When 'drainage' is absent from active_bc, _build_drainage_spd returns None."""
    from unittest.mock import MagicMock
    drain_array = np.ones((3, 3))
    hk = np.ones((1, 3, 3)) * 1e-4

    drainage_bc = MagicMock()
    drainage_bc.value = 0.0
    adapter = _make_bc_adapter({"drainage": drainage_bc}, active_bc=["ocean"])

    result = adapter._build_drainage_spd(drain_array=drain_array, hk=hk)

    assert result is None


def test_west_side_not_activated_leaves_ibound_unchanged():
    """When 'west_side' is absent from active_bc, its column is not set to -1."""
    from unittest.mock import MagicMock
    west_bc = MagicMock()
    west_bc.value = 5.0
    adapter = _make_bc_adapter({"west_side": west_bc}, active_bc=[])

    ibound, strt, _ = adapter._build_initial_heads_and_sides()

    # Column 0 must NOT be constant-head (-1) since west_side is inactive
    assert np.all(ibound[:, :, 0] != -1)


def test_transient_west_side_uses_chd_and_keeps_face_active():
    west_bc = types.SimpleNamespace(value=[5.0, 6.0])
    adapter = _make_bc_adapter({"west_side": west_bc}, active_bc=["west_side"], nper=2)

    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    chd_spd = adapter._build_side_chd()

    assert np.all(ibound[:, :, 0] == 1.0)
    assert np.all(strt[:, :, 0] == 5.0)
    assert chd_spd is not None
    assert chd_spd[0][0] == [0, 0, 0, pytest.approx(5.0), pytest.approx(5.0)]
    assert chd_spd[1][0] == [0, 0, 0, pytest.approx(6.0), pytest.approx(6.0)]


def test_boundary_forcing_constant_is_resolved_in_adapter_without_runtime_binding():
    west_bc = FlowBoundaryConditionConfig(
        id="west_side",
        type="dirichlet",
        units="m",
        application_domain="west side",
        forcing={"mode": "constant", "value": 5.0},
    )
    adapter = _make_bc_adapter({"west_side": west_bc}, active_bc=["west_side"], nper=2)

    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    chd_spd = adapter._build_side_chd()

    assert np.all(ibound[:, :, 0] == 1.0)
    assert np.all(strt[:, :, 0] == 5.0)
    assert chd_spd == {
        0: [[0, 0, 0, 5.0, 5.0], [0, 1, 0, 5.0, 5.0], [0, 2, 0, 5.0, 5.0]],
        1: [[0, 0, 0, 5.0, 5.0], [0, 1, 0, 5.0, 5.0], [0, 2, 0, 5.0, 5.0]],
    }


def test_boundary_forcing_csv_requires_simulation_window():
    west_bc = FlowBoundaryConditionConfig(
        id="west_side",
        type="dirichlet",
        units="m",
        application_domain="west side",
        forcing={
            "mode": "csv",
            "path_file": "dummy.csv",
        },
    )
    adapter = _make_bc_adapter({"west_side": west_bc}, active_bc=["west_side"], nper=2)

    with pytest.raises(ValueError, match="simulation.time is required"):
        adapter._build_initial_heads_and_sides()


def test_merge_chd_payloads_lets_side_override_ocean_corner_cell():
    adapter = _make_bc_adapter({}, active_bc=[], nper=2)
    ocean_chd = {
        0: [[0, 0, 0, 1.0, 1.0]],
        1: [[0, 0, 0, 2.0, 2.0]],
    }
    side_chd = {
        0: [[0, 0, 0, 5.0, 5.0]],
        1: [[0, 0, 0, 6.0, 6.0]],
    }

    merged = adapter._merge_chd_payloads(ocean_chd, side_chd)

    assert merged == {
        0: [[0, 0, 0, 5.0, 5.0]],
        1: [[0, 0, 0, 6.0, 6.0]],
    }
