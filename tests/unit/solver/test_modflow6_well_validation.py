"""WP11 - the MF6 WEL builder rejects out-of-range or inactive well cells early."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.physics.flow.sinks_sources import FlowWellConfig
from hydromodpy.solver.modflow6.builders import build_well_stress_period_data

from ._test_modflow6_boundary_conditions_builders import _build_model, _build_unstructured_model


def _with_well(model, location, *, units="m3/day", value=-86400.0):
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    location=location,
                    units=units,
                    forcing={"kind": "constant", "value": value},
                )
            }
        },
        active_sinks_sources=["wells"],
    )
    return model


def test_well_cell_layer_out_of_range_raises() -> None:
    model = _with_well(_build_model(), {"kind": "cell", "cell": (1, 0, 0)})
    with pytest.raises(ValueError, match=r"W1 layer 1 is outside.*0\.\.0"):
        build_well_stress_period_data(model, 2)


def test_well_cell_on_inactive_cell_raises_flat_mask() -> None:
    model = _build_model()
    model.dem_mask = np.zeros(6, dtype=bool)
    model.dem_mask[4] = True  # cell (0,1,1) -> cell_id 4 is inactive
    _with_well(model, {"kind": "cell", "cell": (0, 1, 1)})
    with pytest.raises(ValueError, match=r"W1 targets an inactive cell.*layer 0, cell 4"):
        build_well_stress_period_data(model, 2)


def test_well_cell_on_inactive_cell_raises_per_layer_mask() -> None:
    mask = np.zeros((2, 6), dtype=bool)
    mask[1, 4] = True  # layer 1, cell 4 inactive; layer 0, cell 4 active

    # W1 in the inactive layer-1 cell raises.
    model = _build_model()
    model.nlay = 2
    model.solver_mesh = SimpleNamespace(inactive_mask=mask)
    _with_well(model, {"kind": "cell", "cell": (1, 1, 1)})
    with pytest.raises(ValueError, match=r"W1.*layer 1.*cell 4"):
        build_well_stress_period_data(model, 1)

    # The same cell in the active layer 0 succeeds.
    model0 = _build_model()
    model0.nlay = 2
    model0.solver_mesh = SimpleNamespace(inactive_mask=mask)
    _with_well(model0, {"kind": "cell", "cell": (0, 1, 1)})
    spd = build_well_stress_period_data(model0, 1)
    assert spd[0] == [[0, 4, pytest.approx(-1.0)]]


def test_well_coordinate_layer_out_of_range_raises_unstructured() -> None:
    model = _build_unstructured_model()
    _with_well(model, {"kind": "absolute_xy", "x": 0.75, "y": 0.25, "layer": 2}, value=-1.0)
    with pytest.raises(ValueError, match=r"W1 layer 2 is outside"):
        build_well_stress_period_data(model, 1)


def test_well_happy_path_unit_conversion_unchanged() -> None:
    model = _with_well(_build_model(), {"kind": "cell", "cell": (0, 0, 0)})
    spd = build_well_stress_period_data(model, 2)
    assert spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert spd[1] == [[0, 0, pytest.approx(-1.0)]]


def test_well_last_active_cell_not_false_rejected() -> None:
    model = _build_model()
    model.dem_mask = np.zeros(6, dtype=bool)  # all active
    _with_well(model, {"kind": "cell", "cell": (0, 1, 2)})  # -> cell_id 5 (the last)
    spd = build_well_stress_period_data(model, 1)
    assert spd[0] == [[0, 5, pytest.approx(-1.0)]]
