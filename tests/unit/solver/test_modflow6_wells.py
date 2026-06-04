from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.physics.flow.sinks_sources import FlowWellConfig
from hydromodpy.solver.modflow6.builders import build_well_stress_period_data

from ._test_modflow6_boundary_conditions_builders import (
    _build_model,
    _build_unstructured_model,
)


def test_modflow6_resolves_well_forcing_without_runtime_binding() -> None:
    model = _build_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    location={"kind": "cell", "cell": (0, 0, 0)},
                    units="m3/day",
                    forcing={"kind": "constant", "value": -86400.0},
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    wel_spd = build_well_stress_period_data(model, 2)

    # DISV: [lay, cell_id, flux] - cell (0,0,0) → cell_id=0
    assert wel_spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, pytest.approx(-1.0)]]


def test_modflow6_resolves_absolute_xy_well_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    location={"kind": "absolute_xy", "x": 0.75, "y": 0.25},
                    flux=-1.0,
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    wel_spd = build_well_stress_period_data(model, 2)

    assert wel_spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, pytest.approx(-1.0)]]


def test_modflow6_coordinate_well_rejects_inherited_cell_payload() -> None:
    model = _build_unstructured_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": {
                    "cell": (0, 0, 1),
                    "location": {"kind": "absolute_xy", "x": 0.75, "y": 0.25, "layer": 0},
                    "flux": -1.0,
                }
            }
        },
        active_sinks_sources=["wells"],
    )

    with pytest.raises(ValueError, match="Extra inputs"):
        build_well_stress_period_data(model, 1)


def test_modflow6_rejects_unstructured_well_outside_runtime_mesh() -> None:
    model = _build_unstructured_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    location={"kind": "absolute_xy", "x": 2.0, "y": 2.0},
                    flux=-1.0,
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    with pytest.raises(ValueError, match="outside the .* mesh domain"):
        build_well_stress_period_data(model, 2)


def test_modflow6_rejects_well_flux_length_mismatch() -> None:
    model = _build_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    location={"kind": "cell", "cell": (0, 0, 0)},
                    flux=[-1.0, -2.0, -3.0],
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    with pytest.raises(ValueError, match="must be 1 or match nper"):
        build_well_stress_period_data(model, 2)


def test_modflow6_flow_adapter_builds_wells_from_forcing_payload() -> None:
    model = _build_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    location={"kind": "cell", "cell": (0, 0, 0)},
                    units="m3/day",
                    forcing={"kind": "constant", "value": -86400.0},
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    wel_spd = build_well_stress_period_data(model, 2)

    assert wel_spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, pytest.approx(-1.0)]]
