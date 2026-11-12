"""
Tests for boundary-condition payload building via FlowToModflowAdapter.

Covers the active_bc gate (ocean CHD, drainage DRN, west-side IBOUND/CHD),
forcing resolution for sides, and CHD payload merging.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.boundaries.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.model.initial.state import HeadRule
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from tests._helpers.model_factory import make_model

from ._test_forcing_adapter_builders import _build_solver_mesh


def _make_bc_adapter(boundary_conditions, active_bc, nper=1, simulation_window=None):
    """Build a minimal FlowToModflowAdapter focused on the BC path."""
    model = make_model(
        boundaries=BoundaryConditionBundle(
            conditions=boundary_conditions, active_ids=tuple(active_bc)
        ),
        initial=HeadRule("custom", 0.0),
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )
    return FlowToModflowAdapter(
        model=model,
        solver_mesh=_build_solver_mesh(nrow=3, ncol=3),
        nper=nper,
        simulation_window=simulation_window,
        sink_fill=False,
    )


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
        forcing={"kind": "constant", "value": 5.0},
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
            "kind": "csv",
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
