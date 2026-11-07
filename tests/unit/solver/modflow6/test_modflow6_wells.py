from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.sinks_sources.wells import FlowWellConfig
from hydromodpy.solver.modflow6.builders.wells import build_well_stress_period_data
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import (
    toy_model,
    two_triangle_model,
)


def test_modflow6_resolves_well_forcing_without_runtime_binding() -> None:
    model = toy_model()
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
    model = two_triangle_model()
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
    model = two_triangle_model()
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
    model = two_triangle_model()
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

    with pytest.raises(ValueError, match="W1 coordinates .* are outside the mesh domain"):
        build_well_stress_period_data(model, 2)


def test_modflow6_rejects_well_flux_length_mismatch() -> None:
    model = toy_model()
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
    model = toy_model()
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


def _model_with_well(model, location: dict, flux: float = -1.0):
    model.flow = SimpleNamespace(
        sinks_sources={"wells": {"W1": FlowWellConfig(location=location, flux=flux)}},
        active_sinks_sources=["wells"],
    )
    return model


def test_modflow6_locates_a_coordinate_well_in_the_cell_of_a_regular_grid() -> None:
    # 2 x 3 cells of 1 m, row 0 north: (1.5, 1.5) is row 0, column 1.
    model = _model_with_well(toy_model(), {"kind": "absolute_xy", "x": 1.5, "y": 1.5})

    assert build_well_stress_period_data(model, 1)[0] == [[0, 1, pytest.approx(-1.0)]]


def test_modflow6_puts_a_well_on_the_east_or_south_border_in_the_last_column_or_row() -> None:
    model = _model_with_well(toy_model(), {"kind": "absolute_xy", "x": 3.0, "y": 0.0})

    assert build_well_stress_period_data(model, 1)[0] == [[0, 5, pytest.approx(-1.0)]]


def test_modflow6_puts_a_well_on_a_shared_edge_in_the_cell_east_or_south_of_it() -> None:
    model = _model_with_well(toy_model(), {"kind": "absolute_xy", "x": 1.0, "y": 1.0})

    # Column edge x = 1 opens column 1; row edge y = 1 opens the southern row 1.
    assert build_well_stress_period_data(model, 1)[0] == [[0, 4, pytest.approx(-1.0)]]


def test_modflow6_reads_a_relative_well_over_the_extent_of_the_mesh() -> None:
    model = _model_with_well(toy_model(), {"kind": "relative_xy", "x_rel": 0.9, "y_rel": 0.1})

    # 0.9 of 3 m east, 0.1 of 2 m north of the south side: row 1, column 2.
    assert build_well_stress_period_data(model, 1)[0] == [[0, 5, pytest.approx(-1.0)]]


def test_modflow6_locates_a_coordinate_well_in_the_triangle_that_holds_it() -> None:
    model = two_triangle_model()
    _model_with_well(model, {"kind": "absolute_xy", "x": 0.1, "y": 0.8})

    assert build_well_stress_period_data(model, 1)[0] == [[0, 1, pytest.approx(-1.0)]]


def test_modflow6_reads_a_relative_well_over_the_extent_of_a_triangle_mesh() -> None:
    model = two_triangle_model()
    _model_with_well(model, {"kind": "relative_xy", "x_rel": 0.9, "y_rel": 0.2})

    assert build_well_stress_period_data(model, 1)[0] == [[0, 0, pytest.approx(-1.0)]]


def test_modflow6_refuses_a_lay_row_col_address_on_a_triangle_mesh() -> None:
    model = two_triangle_model()
    _model_with_well(model, {"kind": "cell", "cell": (0, 0, 1)})

    with pytest.raises(ValueError, match=r"addressing needs a regular grid"):
        build_well_stress_period_data(model, 1)


def test_modflow6_refuses_a_lay_row_col_address_outside_the_grid() -> None:
    model = _model_with_well(toy_model(), {"kind": "cell", "cell": (0, 2, 0)})

    with pytest.raises(ValueError, match="row is outside the grid"):
        build_well_stress_period_data(model, 1)


def test_a_coordinate_well_without_a_layer_goes_to_the_top_active_cell() -> None:
    model = toy_model()
    base = model.solver_mesh
    idomain = np.ones((2, 6), dtype=int)
    idomain[0, 0] = 0
    model.solver_mesh = SolverMesh(
        cell_mesh=base.cell_mesh,
        top=base.top,
        botm=np.vstack([base.top - 4.0, base.top - 9.0]),
        idomain=idomain,
    )
    model.nlay = 2
    wells = {
        "W1": FlowWellConfig(location={"kind": "absolute_xy", "x": 0.5, "y": 1.5}, flux=-1.0),
        "W2": FlowWellConfig(location={"kind": "absolute_xy", "x": 1.5, "y": 1.5}, flux=-1.0),
    }
    model.flow = SimpleNamespace(sinks_sources={"wells": wells}, active_sinks_sources=["wells"])

    wel_spd = build_well_stress_period_data(model, 1)

    assert sorted((row[0], row[1]) for row in wel_spd[0]) == [(0, 1), (1, 0)]


# WP11 - the MF6 WEL builder rejects out-of-range or inactive well cells early.


def _with_well(model, location, *, units="m3/day", value=-86400.0):
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
    model = _with_well(toy_model(), {"kind": "cell", "cell": (1, 0, 0)})
    with pytest.raises(ValueError, match=r"W1 layer 1 is outside.*0\.\.0"):
        build_well_stress_period_data(model, 2)


def test_well_cell_on_inactive_cell_raises() -> None:
    model = toy_model()
    mask = np.zeros((1, 6), dtype=bool)
    mask[0, 4] = True  # cell (0,1,1) -> cell_id 4 is inactive
    model.solver_mesh = replace(model.solver_mesh, idomain=np.where(mask, 0, 1))
    _with_well(model, {"kind": "cell", "cell": (0, 1, 1)})
    with pytest.raises(ValueError, match=r"W1 targets an inactive cell.*layer 0, cell 4"):
        build_well_stress_period_data(model, 2)


def test_well_cell_on_inactive_cell_raises_per_layer_mask() -> None:
    mask = np.zeros((2, 6), dtype=bool)
    mask[1, 4] = True  # layer 1, cell 4 inactive; layer 0, cell 4 active

    two_layers = replace(
        toy_model().solver_mesh, botm=np.zeros((2, 6)), idomain=np.where(mask, 0, 1)
    )

    # W1 in the inactive layer-1 cell raises.
    model = toy_model()
    model.nlay = 2
    model.solver_mesh = two_layers
    _with_well(model, {"kind": "cell", "cell": (1, 1, 1)})
    with pytest.raises(ValueError, match=r"W1.*layer 1.*cell 4"):
        build_well_stress_period_data(model, 1)

    # The same cell in the active layer 0 succeeds.
    model0 = toy_model()
    model0.nlay = 2
    model0.solver_mesh = two_layers
    _with_well(model0, {"kind": "cell", "cell": (0, 1, 1)})
    spd = build_well_stress_period_data(model0, 1)
    assert spd[0] == [[0, 4, pytest.approx(-1.0)]]


def test_well_coordinate_layer_out_of_range_raises_unstructured() -> None:
    model = two_triangle_model()
    _with_well(model, {"kind": "absolute_xy", "x": 0.75, "y": 0.25, "layer": 2}, value=-1.0)
    with pytest.raises(ValueError, match=r"W1 layer 2 is outside"):
        build_well_stress_period_data(model, 1)


def test_well_happy_path_unit_conversion_unchanged() -> None:
    model = _with_well(toy_model(), {"kind": "cell", "cell": (0, 0, 0)})
    spd = build_well_stress_period_data(model, 2)
    assert spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert spd[1] == [[0, 0, pytest.approx(-1.0)]]


def test_well_last_active_cell_not_false_rejected() -> None:
    model = toy_model()
    _with_well(model, {"kind": "cell", "cell": (0, 1, 2)})  # -> cell_id 5 (the last)
    spd = build_well_stress_period_data(model, 1)
    assert spd[0] == [[0, 5, pytest.approx(-1.0)]]
