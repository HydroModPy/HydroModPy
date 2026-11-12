"""Constant-head (CHD) cells of the side and stream boundaries of a MODFLOW 6 grid.

Heads are in m. A side boundary picks the cells along one edge of the grid, a
stream boundary the cells of the river chain, and a support label picks either by
name. A head below the cell bottom is refused.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.boundaries.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.model.initial.state import HeadRule
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    apply_side_boundary_start_heads,
    build_side_boundary_chd_spd,
    build_stream_boundary_chd_spd,
    refuse_constant_heads_below_bottom,
)
from hydromodpy.solver.modflow6.builders.initial_conditions import build_start_heads
from tests._helpers.mf6_toy_models import (
    regular_solver_mesh,
    toy_model,
    two_triangle_model,
)


def bound(model, conditions: dict, active: tuple[str, ...] | None = None, **inputs):
    """Give the model these boundary conditions, all active unless told otherwise."""
    bundle = BoundaryConditionBundle(
        conditions=conditions, active_ids=tuple(conditions) if active is None else active
    )
    model.inputs = replace(model.inputs, boundaries=bundle, **inputs)
    return model


def head(value, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(value=value, **kwargs)


def side_model_with_heads(west: float, east: float):
    # On the 2 x 3 toy grid the west cells are 0 and 3, the east cells 2 and 5.
    return bound(toy_model(), {"west_side": head(west), "east_side": head(east)})


def refuse(model, *, side=None, stream=None, idomain=None, **kwargs) -> None:
    refuse_constant_heads_below_bottom(
        model,
        botm=np.zeros((1, 6)),
        idomain=np.ones((1, 6), dtype=int) if idomain is None else idomain,
        ocean_spd={},
        stream_spd=stream or {},
        side_spd=side or {},
        **kwargs,
    )


def test_side_chd_from_scalar_and_transient_heads() -> None:
    model = bound(toy_model(), {"west_side": head(10.0), "east_side": head([20.0, 21.0])})

    chd_spd = build_side_boundary_chd_spd(model)

    # DISV record is [layer, cell, head]. The last cell of east_side is 2 + 3 = 5.
    assert chd_spd[0][0] == [0, 0, pytest.approx(10.0)]
    assert chd_spd[0][-1] == [0, 5, pytest.approx(20.0)]
    assert chd_spd[1][-1] == [0, 5, pytest.approx(21.0)]


def test_boundary_forcing_needs_no_runtime_binding() -> None:
    east = FlowBoundaryConditionConfig(
        id="east_side",
        kind="dirichlet",
        units="cm",
        application_domain="east side",
        forcing={"kind": "constant", "value": 20.0},
    )

    chd_spd = build_side_boundary_chd_spd(bound(toy_model(), {"east_side": east}))

    assert chd_spd[0][-1] == [0, 5, pytest.approx(0.2)]
    assert chd_spd[1][-1] == [0, 5, pytest.approx(0.2)]


def test_side_chd_on_two_triangles() -> None:
    model = bound(two_triangle_model(), {"west_side": head(10.0), "east_side": head([20.0, 21.0])})

    chd_spd = build_side_boundary_chd_spd(model)

    period0 = sorted(chd_spd[0], key=lambda item: item[1])
    period1 = sorted(chd_spd[1], key=lambda item: item[1])
    assert period0 == [[0, 0, pytest.approx(20.0)], [0, 1, pytest.approx(10.0)]]
    assert period1 == [[0, 0, pytest.approx(21.0)], [0, 1, pytest.approx(10.0)]]


def test_side_start_heads_on_two_triangles() -> None:
    model = bound(two_triangle_model(), {"west_side": head([7.0, 8.0])})

    updated = apply_side_boundary_start_heads(model, np.zeros((1, 2)))

    assert updated[0, 0] == pytest.approx(0.0)
    assert updated[0, 1] == pytest.approx(7.0)


def test_stream_chd_on_two_triangles() -> None:
    model = bound(two_triangle_model(river_internal_edge=True), {"stream": head(7.0)})

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

    assert stream_mask.tolist() == [True, True]
    assert chd_spd[0] == [[0, 0, pytest.approx(7.0)], [0, 1, pytest.approx(7.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(7.0)], [0, 1, pytest.approx(7.0)]]


def test_stream_start_heads_on_two_triangles() -> None:
    model = bound(
        two_triangle_model(river_internal_edge=True),
        {"stream": head(7.0)},
        initial=HeadRule("custom", 2.0),
    )

    strt = build_start_heads(model, model.solver_mesh)

    assert np.allclose(strt[0], [7.0, 7.0])


def test_support_label_picks_the_side_cells() -> None:
    east = FlowBoundaryConditionConfig(
        id="east_side",
        value=6.0,
        units="m",
        kind="dirichlet",
        application_domain="east side",
        support_label="east_custom",
    )
    model = bound(
        two_triangle_model(boundary_labels_by_edge_id={1: "east_custom"}),
        {"west_side": head(10.0), "east_side": east},
        active=("east_side",),
    )

    chd_spd = build_side_boundary_chd_spd(model)

    assert chd_spd[0] == [[0, 0, pytest.approx(6.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(6.0)]]


def test_support_label_picks_the_stream_cells() -> None:
    stream = FlowBoundaryConditionConfig(
        id="stream",
        value=5.0,
        units="m",
        kind="dirichlet",
        application_domain="top",
        support_label="ditch_custom",
    )
    model = bound(
        two_triangle_model(boundary_labels_by_edge_id={0: "ditch_custom"}), {"stream": stream}
    )

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

    assert stream_mask.tolist() == [True, False]
    assert chd_spd[0] == [[0, 0, pytest.approx(5.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(5.0)]]


@pytest.mark.parametrize("support_label", ["east_custom", "boundary:east_custom"])
def test_a_group_is_read_by_its_family_name_or_its_bare_name(support_label) -> None:
    model = bound(
        two_triangle_model(boundary_labels_by_edge_id={1: "east_custom"}),
        {"east_side": head(6.0, units="m", support_label=support_label)},
    )

    assert build_side_boundary_chd_spd(model)[0] == [[0, 0, pytest.approx(6.0)]]


def test_a_label_wins_over_the_side_on_a_regular_grid() -> None:
    model = bound(
        toy_model(),
        {"west_side": head(3.0, units="m", support_label="boundary:south")},
    )

    # The south row of the 2 x 3 grid, not the west column.
    assert [row[1] for row in build_side_boundary_chd_spd(model)[0]] == [3, 4, 5]


def test_stream_chd_on_the_river_chain_of_a_regular_grid() -> None:
    model = bound(toy_model(), {"stream": head(7.0)})
    model.solver_mesh = regular_solver_mesh(2, 3, river=LineString([(0.5, 1.5), (1.5, 0.5)]))

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

    chain_cells = np.concatenate(
        [chain.cell_ids for chain in model.solver_mesh.cell_mesh.chains("rivers")]
    )
    assert np.flatnonzero(stream_mask).tolist() == sorted(set(chain_cells.tolist()))
    assert stream_mask.sum() >= 2
    assert [row[1] for row in chd_spd[0]] == np.flatnonzero(stream_mask).tolist()


def test_a_head_below_the_bottom_names_boundary_and_cell() -> None:
    model = side_model_with_heads(west=-5.0, east=5.0)

    with pytest.raises(SolverInputError) as excinfo:
        refuse(model, side=build_side_boundary_chd_spd(model), structured_shape=(2, 3))

    message = str(excinfo.value)
    assert "flow.bc.west_side: 2 cell(s)" in message
    assert "layer 0 row 0 column 0 (head -5.00 m, bottom 0.00 m, period 1)" in message
    assert "layer 0 row 1 column 0" in message
    assert "east_side" not in message


def test_a_head_on_an_inactive_cell_passes() -> None:
    model = side_model_with_heads(west=-5.0, east=5.0)
    idomain = np.ones((1, 6), dtype=int)
    idomain[0, [0, 3]] = 0  # the two west cells

    refuse(model, side=build_side_boundary_chd_spd(model), idomain=idomain)


def test_a_stream_head_overwritten_by_a_side_head_is_not_checked() -> None:
    model = side_model_with_heads(west=5.0, east=5.0)
    side = build_side_boundary_chd_spd(model)
    # The stream claims west cell 0 with a head below the bottom and the side
    # writes over it, so MODFLOW 6 receives the side head only.
    refuse(model, side=side, stream={0: [[0, 0, -1.0]], 1: [[0, 0, -1.0]]})

    with pytest.raises(SolverInputError, match=r"flow\.bc\.stream: 1 cell\(s\): layer 0 cell 1"):
        refuse(model, side=side, stream={0: [[0, 1, -1.0]], 1: [[0, 1, -1.0]]})


def mesh_free_model() -> SimpleNamespace:
    model = bound(toy_model(), {"west_side": head(1.0)})
    model.solver_mesh = None
    return model


REFUSALS = [
    pytest.param(
        bound(two_triangle_model(), {"east_side": head(6.0, units="m", support_label="nowhere")}),
        build_side_boundary_chd_spd,
        "support_label='nowhere' did not match",
        id="label matches no cell",
    ),
    pytest.param(
        bound(toy_model(), {"stream": head(7.0)}),
        build_stream_boundary_chd_spd,
        "selected runtime mesh support is empty",
        id="no river cells",
    ),
    pytest.param(
        mesh_free_model(),
        build_side_boundary_chd_spd,
        "reads the cells of the solver mesh",
        id="no solver mesh",
    ),
]


@pytest.mark.parametrize(("model", "build", "match"), REFUSALS)
def test_refusals(model, build, match) -> None:
    with pytest.raises(ValueError, match=match):
        build(model)
