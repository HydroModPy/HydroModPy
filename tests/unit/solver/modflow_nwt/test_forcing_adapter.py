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

from hydromodpy.core.grid_reference import GridReference
from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig, FlowWellConfig
from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter


def _build_solver_mesh(nrow=1, ncol=1, nlay=1, dx=1.0, dy=1.0, xoff=0.0, yoff=0.0):
    """Build a minimal structured SolverMesh for adapter tests."""
    top = np.zeros((nrow, ncol), dtype=float)
    botm = np.zeros((nlay, nrow, ncol), dtype=float) - 10.0
    return SolverMesh.from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=top,
        botm=botm,
        dx=dx,
        dy=dy,
        xoff=xoff,
        yoff=yoff,
    )


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


def test_recharge_scalar_broadcast_to_all_periods():
    cfg = FlowRechargeConfig(values=0.001, units="mm/day")
    adapter = _make_adapter(cfg, "transient", nper=3)

    rch_data = adapter._build_recharge_payload()

    assert all(rch_data[k] == pytest.approx(1.0e-6 / 86400.0) for k in range(3))


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
# active_sinks_sources gate tests
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
    adapter = FlowToModflowAdapter(
        flow=flow,
        domain=None,
        solver_mesh=_build_solver_mesh(),
        nper=2,
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
    grid = GridReference(
        n_cells=20,
        bounds=(0.0, 0.0, 250.0, 400.0),
        crs=None,
        structured_shape=(4, 5),
        cell_size_hint=50.0,
    )
    adapter = FlowToModflowAdapter(
        flow=flow,
        domain=None,
        solver_mesh=_build_solver_mesh(nrow=4, ncol=5, nlay=2, dx=50.0, dy=100.0),
        nper=2,
        grid=grid,
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
    grid = GridReference(
        n_cells=20,
        bounds=(100.0, 200.0, 150.0, 240.0),
        crs=None,
        structured_shape=(4, 5),
        cell_size_hint=10.0,
    )
    adapter = FlowToModflowAdapter(
        flow=flow,
        domain=None,
        solver_mesh=_build_solver_mesh(nrow=4, ncol=5, dx=10.0, dy=10.0, xoff=100.0, yoff=200.0),
        nper=2,
        grid=grid,
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
    adapter = FlowToModflowAdapter(
        flow=flow,
        domain=None,
        solver_mesh=_build_solver_mesh(),
        nper=2,
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
    flow = types.SimpleNamespace(
        boundary_conditions=boundary_conditions,
        initial_conditions=types.SimpleNamespace(h=types.SimpleNamespace(type="custom", value=0.0)),
        flow_regime="transient",
        active_sinks_sources=[],
        active_bc=active_bc,
        sinks_sources={},
        config=None,
    )
    return FlowToModflowAdapter(
        flow=flow,
        domain=None,
        solver_mesh=_build_solver_mesh(nrow=3, ncol=3),
        nper=nper,
        simulation_window=simulation_window,
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
        units="cm",
        application_domain="west side",
        forcing={"mode": "constant", "value": 5.0},
    )
    adapter = _make_bc_adapter({"west_side": west_bc}, active_bc=["west_side"], nper=2)

    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    chd_spd = adapter._build_side_chd()

    assert np.all(ibound[:, :, 0] == 1.0)
    assert np.all(strt[:, :, 0] == 0.05)
    assert chd_spd == {
        0: [[0, 0, 0, 0.05, 0.05], [0, 1, 0, 0.05, 0.05], [0, 2, 0, 0.05, 0.05]],
        1: [[0, 0, 0, 0.05, 0.05], [0, 1, 0, 0.05, 0.05], [0, 2, 0, 0.05, 0.05]],
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
