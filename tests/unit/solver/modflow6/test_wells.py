"""The MF6 WEL builder puts each well in the cell that holds it and gives its rate in m3/s.

The toy mesh is 2 x 3 square cells of 1 m, row 0 in the north, so cell ids run 0..2 in the north
row and 3..5 in the south row. The triangle mesh holds two triangles. A rate of -1 m3/s is a
withdrawal of 86400 m3/day.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hydromodpy.model.sinks_sources.wells import FlowWellConfig
from hydromodpy.solver.modflow6.builders.wells import build_well_stress_period_data
from tests._helpers.mf6_toy_models import toy_model, two_triangle_model

NPER = 2


def with_wells(model, wells: dict):
    model.inputs = replace(model.inputs, wells=wells, active_sinks_sources=("wells",))
    return model


def flux_well(location: dict, flux=-1.0) -> FlowWellConfig:
    return FlowWellConfig(location=location, flux=flux)


def daily_well(location: dict, value: float = -86400.0) -> FlowWellConfig:
    return FlowWellConfig(
        location=location, units="m3/day", forcing={"kind": "constant", "value": value}
    )


# Expected cell id of a well. The east and south borders belong to the last column and row, and
# a shared edge belongs to the cell east or south of it.
WELL_CELLS = [
    pytest.param(
        toy_model, flux_well({"kind": "cell", "cell": (0, 0, 0)}), 0, id="layer row column"
    ),
    pytest.param(
        toy_model, flux_well({"kind": "absolute_xy", "x": 1.5, "y": 1.5}), 1, id="xy in a cell"
    ),
    pytest.param(
        toy_model,
        flux_well({"kind": "absolute_xy", "x": 3.0, "y": 0.0}),
        5,
        id="xy on the east and south border",
    ),
    pytest.param(
        toy_model,
        flux_well({"kind": "absolute_xy", "x": 1.0, "y": 1.0}),
        4,
        id="xy on a shared edge",
    ),
    pytest.param(
        toy_model,
        # 0.9 of 3 m east, 0.1 of 2 m north of the south side, row 1 and column 2.
        flux_well({"kind": "relative_xy", "x_rel": 0.9, "y_rel": 0.1}),
        5,
        id="relative xy",
    ),
    pytest.param(
        two_triangle_model,
        flux_well({"kind": "absolute_xy", "x": 0.75, "y": 0.25}),
        0,
        id="xy in a triangle",
    ),
    pytest.param(
        two_triangle_model,
        flux_well({"kind": "absolute_xy", "x": 0.1, "y": 0.8}),
        1,
        id="xy in the other triangle",
    ),
    pytest.param(
        two_triangle_model,
        flux_well({"kind": "relative_xy", "x_rel": 0.9, "y_rel": 0.2}),
        0,
        id="relative xy on triangles",
    ),
]


@pytest.mark.parametrize(("make_model", "well", "cell_id"), WELL_CELLS)
def test_well_cell(make_model, well, cell_id) -> None:
    model = with_wells(make_model(), {"W1": well})
    spd = build_well_stress_period_data(model, NPER)
    # DISV rows are [layer, cell_id, rate].
    for period in range(NPER):
        assert spd[period] == [[0, cell_id, pytest.approx(-1.0)]]


# A rate given as a forcing in m3/day is converted to m3/s, and the last cell is not refused.
DAILY_WELLS = [
    pytest.param({"kind": "cell", "cell": (0, 0, 0)}, 0, id="first cell"),
    pytest.param({"kind": "cell", "cell": (0, 1, 2)}, 5, id="last cell"),
]


@pytest.mark.parametrize(("location", "cell_id"), DAILY_WELLS)
def test_rate_in_m3_per_day(location, cell_id) -> None:
    model = with_wells(toy_model(), {"W1": daily_well(location)})
    spd = build_well_stress_period_data(model, NPER)
    for period in range(NPER):
        assert spd[period] == [[0, cell_id, pytest.approx(-1.0)]]


def test_well_on_the_active_layer_of_a_masked_column() -> None:
    mask = np.zeros((2, 6), dtype=bool)
    mask[1, 4] = True  # layer 1, cell 4 is inactive and layer 0, cell 4 is active
    model = toy_model()
    model.nlay = 2
    model.solver_mesh = replace(
        model.solver_mesh, botm=np.zeros((2, 6)), idomain=np.where(mask, 0, 1)
    )
    with_wells(model, {"W1": daily_well({"kind": "cell", "cell": (0, 1, 1)})})
    assert build_well_stress_period_data(model, 1)[0] == [[0, 4, pytest.approx(-1.0)]]


WELL_REFUSALS = [
    pytest.param(
        two_triangle_model,
        {
            "cell": (0, 0, 1),
            "location": {"kind": "absolute_xy", "x": 0.75, "y": 0.25, "layer": 0},
            "flux": -1.0,
        },
        1,
        "Extra inputs",
        id="coordinate well with an inherited cell",
    ),
    pytest.param(
        two_triangle_model,
        flux_well({"kind": "absolute_xy", "x": 2.0, "y": 2.0}),
        2,
        "W1 coordinates .* are outside the mesh domain",
        id="outside the triangle mesh",
    ),
    pytest.param(
        toy_model,
        flux_well({"kind": "cell", "cell": (0, 0, 0)}, flux=[-1.0, -2.0, -3.0]),
        2,
        "must be 1 or match nper",
        id="flux length differs from nper",
    ),
    pytest.param(
        two_triangle_model,
        flux_well({"kind": "cell", "cell": (0, 0, 1)}),
        1,
        "addressing needs a regular grid",
        id="layer row column on triangles",
    ),
    pytest.param(
        toy_model,
        flux_well({"kind": "cell", "cell": (0, 2, 0)}),
        1,
        "row is outside the grid",
        id="row outside the grid",
    ),
    pytest.param(
        toy_model,
        daily_well({"kind": "cell", "cell": (1, 0, 0)}),
        2,
        r"W1 layer 1 is outside.*0\.\.0",
        id="layer outside the grid",
    ),
    pytest.param(
        two_triangle_model,
        daily_well({"kind": "absolute_xy", "x": 0.75, "y": 0.25, "layer": 2}, value=-1.0),
        1,
        r"W1 layer 2 is outside",
        id="layer outside on triangles",
    ),
]


@pytest.mark.parametrize(("make_model", "well", "nper", "message"), WELL_REFUSALS)
def test_refusals(make_model, well, nper, message) -> None:
    model = with_wells(make_model(), {"W1": well})
    with pytest.raises(ValueError, match=message):
        build_well_stress_period_data(model, nper)


def test_inactive_cell_is_refused() -> None:
    model = toy_model()
    mask = np.zeros((1, 6), dtype=bool)
    mask[0, 4] = True  # cell (0, 1, 1) is cell 4
    model.solver_mesh = replace(model.solver_mesh, idomain=np.where(mask, 0, 1))
    with_wells(model, {"W1": daily_well({"kind": "cell", "cell": (0, 1, 1)})})
    with pytest.raises(ValueError, match=r"W1 targets an inactive cell.*layer 0, cell 4"):
        build_well_stress_period_data(model, NPER)


def test_inactive_cell_of_the_second_layer_is_refused() -> None:
    mask = np.zeros((2, 6), dtype=bool)
    mask[1, 4] = True
    model = toy_model()
    model.nlay = 2
    model.solver_mesh = replace(
        model.solver_mesh, botm=np.zeros((2, 6)), idomain=np.where(mask, 0, 1)
    )
    with_wells(model, {"W1": daily_well({"kind": "cell", "cell": (1, 1, 1)})})
    with pytest.raises(ValueError, match=r"W1.*layer 1.*cell 4"):
        build_well_stress_period_data(model, 1)
