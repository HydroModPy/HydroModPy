"""
Tests for WEL stress-period building via FlowToModflowAdapter._build_well_stress_period_data.

Covers the active_sinks_sources gate for wells plus location resolution
(cell / absolute_xy / relative_xy) and forcing resolution.

Asserts on the private ``_build_well_stress_period_data`` decision unit: the
public ``build()`` path needs a full flow (initial_conditions.h, hk/sy/ss) and
domain, so it cannot reach ``wel_spd`` with these minimal fixtures.
"""

from __future__ import annotations

import types

import pytest

from hydromodpy.core.grid_reference import GridReference
from hydromodpy.physics.flow.sinks_sources import FlowWellConfig
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter

from ._test_forcing_adapter_builders import _build_solver_mesh


def test_wells_not_activated_returns_empty_spd():
    """When 'wells' is absent from active_sinks_sources, WEL payload is empty."""

    flow = types.SimpleNamespace(
        sinks_sources={
            "recharge": None,
            "wells": {
                "W1": FlowWellConfig(location={"kind": "cell", "cell": (0, 0, 0)}, flux=-1e-4)
            },
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
                    location={"kind": "absolute_xy", "layer": 1, "x": 125.0, "y": 365.0},
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
                    location={
                        "kind": "relative_xy",
                        "layer": 0,
                        "x_rel": 0.4,
                        "y_rel": 0.25,
                    },
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


def test_well_absolute_xy_outside_grid_raises():
    flow = types.SimpleNamespace(
        sinks_sources={
            "recharge": None,
            "wells": {
                "W1": FlowWellConfig(
                    location={"kind": "absolute_xy", "layer": 0, "x": 1000.0, "y": 1000.0},
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
        solver_mesh=_build_solver_mesh(nrow=4, ncol=5, nlay=1, dx=50.0, dy=100.0),
        nper=2,
        grid=grid,
        sink_fill=False,
    )

    with pytest.raises(ValueError, match="outside the structured solver grid extent"):
        adapter._build_well_stress_period_data()


def test_well_flux_length_mismatch_raises():
    flow = types.SimpleNamespace(
        sinks_sources={
            "recharge": None,
            "wells": {
                "W1": FlowWellConfig(
                    location={"kind": "cell", "cell": (0, 0, 0)},
                    flux=[-1e-4, -2e-4, -3e-4],
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

    with pytest.raises(ValueError, match="must be 1 or match nper"):
        adapter._build_well_stress_period_data()


def test_well_relative_xy_defaults_to_layer_zero():
    well = FlowWellConfig(location={"kind": "relative_xy", "x_rel": 0.5, "y_rel": 0.5}, flux=-1e-4)
    assert well.location.layer == 0


def test_well_forcing_constant_is_resolved_in_adapter_without_runtime_binding():
    flow = types.SimpleNamespace(
        sinks_sources={
            "recharge": None,
            "wells": {
                "W1": FlowWellConfig(
                    location={"kind": "cell", "cell": (0, 0, 0)},
                    units="m3/day",
                    forcing={"kind": "constant", "value": -86400.0},
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
