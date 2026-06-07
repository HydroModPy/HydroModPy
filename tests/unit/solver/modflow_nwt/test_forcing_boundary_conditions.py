"""
Tests for boundary-condition payload building via FlowToModflowAdapter.

Covers the active_bc gate (ocean CHD, drainage DRN, west-side IBOUND/CHD),
forcing resolution for sides, and CHD payload merging.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import numpy as np
import pytest

from hydromodpy.physics.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter

from ._test_forcing_adapter_builders import _build_solver_mesh


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
    drain_array = np.ones((3, 3))
    hk = np.ones((1, 3, 3)) * 1e-4

    drainage_bc = MagicMock()
    drainage_bc.value = 0.0
    adapter = _make_bc_adapter({"drainage": drainage_bc}, active_bc=["ocean"])

    result = adapter._build_drainage_spd(drain_array=drain_array, hk=hk)

    assert result is None


def test_west_side_not_activated_leaves_ibound_unchanged():
    """When 'west_side' is absent from active_bc, its column is not set to -1."""
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
        kind="dirichlet",
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
        kind="dirichlet",
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
