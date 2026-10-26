from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.physics.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.physics.flow.initial_conditions import FlowICCustom, FlowInitialConditions
from hydromodpy.solver.modflow6.builders import (
    apply_side_boundary_start_heads,
    build_side_boundary_chd_spd,
    build_start_heads,
    build_stream_boundary_chd_spd,
    refuse_constant_heads_below_bottom,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

from ._test_modflow6_boundary_conditions_builders import (
    _build_model,
    _build_unstructured_model,
    regular_solver_mesh,
)


def test_modflow6_builds_chd_from_scalar_and_transient_side_boundaries() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=10.0),
            "east_side": SimpleNamespace(value=[20.0, 21.0]),
        },
        active_bc=["west_side", "east_side"],
    )

    chd_spd = build_side_boundary_chd_spd(model)

    # DISV format: [lay, cell_id, head]
    # west_side cells: row0*3+0=0, row1*3+0=3
    # east_side cells: row0*3+2=2, row1*3+2=5
    assert chd_spd[0][0] == [0, 0, pytest.approx(10.0)]
    assert chd_spd[0][-1] == [0, 5, pytest.approx(20.0)]
    assert chd_spd[1][-1] == [0, 5, pytest.approx(21.0)]


def test_modflow6_applies_first_boundary_value_to_start_heads() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "north_side": SimpleNamespace(value=[7.0, 8.0]),
        },
        active_bc=["north_side"],
    )
    # strt is now flat (nlay, ncpl)
    strt = np.zeros((1, 6), dtype=float)

    updated = apply_side_boundary_start_heads(model, strt)

    # North side cell_ids for 2x3 grid: 0, 1, 2
    assert np.all(updated[:, :3] == 7.0)
    assert np.all(updated[:, 3:] == 0.0)


def test_modflow6_resolves_boundary_forcing_without_runtime_binding() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "east_side": FlowBoundaryConditionConfig(
                id="east_side",
                kind="dirichlet",
                units="cm",
                application_domain="east side",
                forcing={"mode": "constant", "value": 20.0},
            )
        },
        active_bc=["east_side"],
    )

    chd_spd = build_side_boundary_chd_spd(model)

    # DISV: [lay, cell_id, head] - east_side last cell_id=5
    assert chd_spd[0][-1] == [0, 5, pytest.approx(0.2)]
    assert chd_spd[1][-1] == [0, 5, pytest.approx(0.2)]


def test_modflow6_builds_side_boundary_chd_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=10.0),
            "east_side": SimpleNamespace(value=[20.0, 21.0]),
        },
        active_bc=["west_side", "east_side"],
    )

    chd_spd = build_side_boundary_chd_spd(model)

    period0 = sorted(chd_spd[0], key=lambda item: item[1])
    period1 = sorted(chd_spd[1], key=lambda item: item[1])
    assert period0 == [[0, 0, pytest.approx(20.0)], [0, 1, pytest.approx(10.0)]]
    assert period1 == [[0, 0, pytest.approx(21.0)], [0, 1, pytest.approx(10.0)]]


def test_modflow6_applies_side_boundary_start_heads_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=[7.0, 8.0]),
        },
        active_bc=["west_side"],
    )
    strt = np.zeros((1, 2), dtype=float)

    updated = apply_side_boundary_start_heads(model, strt)

    assert updated[0, 0] == pytest.approx(0.0)
    assert updated[0, 1] == pytest.approx(7.0)


def test_modflow6_builds_stream_boundary_chd_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model(river_internal_edge=True)
    model.flow = SimpleNamespace(
        boundary_conditions={
            "stream": SimpleNamespace(value=7.0),
        },
        active_bc=["stream"],
    )

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

    assert stream_mask.tolist() == [True, True]
    assert chd_spd[0] == [[0, 0, pytest.approx(7.0)], [0, 1, pytest.approx(7.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(7.0)], [0, 1, pytest.approx(7.0)]]


def test_modflow6_applies_stream_start_heads_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model(river_internal_edge=True)
    model.flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(h=FlowICCustom(id="h", value=2.0)),
        boundary_conditions={
            "stream": SimpleNamespace(value=7.0),
        },
        active_bc=["stream"],
    )

    strt = build_start_heads(model, model.solver_mesh)

    assert np.allclose(strt[0], [7.0, 7.0])


def test_modflow6_uses_support_label_for_side_boundary_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model(boundary_labels_by_edge_id={1: "east_custom"})
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=10.0),
            "east_side": FlowBoundaryConditionConfig(
                id="east_side",
                value=6.0,
                units="m",
                kind="dirichlet",
                application_domain="east side",
                support_label="east_custom",
            ),
        },
        active_bc=["east_side"],
    )

    chd_spd = build_side_boundary_chd_spd(model)

    assert chd_spd[0] == [[0, 0, pytest.approx(6.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(6.0)]]


def test_modflow6_uses_support_label_for_stream_boundary_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model(boundary_labels_by_edge_id={0: "ditch_custom"})
    model.flow = SimpleNamespace(
        boundary_conditions={
            "stream": FlowBoundaryConditionConfig(
                id="stream",
                value=5.0,
                units="m",
                kind="dirichlet",
                application_domain="top",
                support_label="ditch_custom",
            ),
        },
        active_bc=["stream"],
    )

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

    assert stream_mask.tolist() == [True, False]
    assert chd_spd[0] == [[0, 0, pytest.approx(5.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(5.0)]]


def _side_model_with_heads(west: float, east: float):
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=west),
            "east_side": SimpleNamespace(value=east),
        },
        active_bc=["west_side", "east_side"],
    )
    return model


def test_a_side_head_below_the_cell_bottom_is_refused_by_boundary_and_cell() -> None:
    model = _side_model_with_heads(west=-5.0, east=5.0)
    side = build_side_boundary_chd_spd(model)
    botm = np.zeros((1, 6), dtype=float)

    with pytest.raises(SolverInputError) as excinfo:
        refuse_constant_heads_below_bottom(
            model,
            botm=botm,
            idomain=np.ones((1, 6), dtype=int),
            ocean_spd={},
            stream_spd={},
            side_spd=side,
            structured_shape=(2, 3),
        )

    message = str(excinfo.value)
    assert "flow.bc.west_side: 2 cell(s)" in message
    assert "layer 0 row 0 column 0 (head -5.00 m, bottom 0.00 m, period 1)" in message
    assert "layer 0 row 1 column 0" in message
    assert "east_side" not in message


def test_a_side_head_above_the_bottom_or_on_an_inactive_cell_passes() -> None:
    model = _side_model_with_heads(west=-5.0, east=5.0)
    side = build_side_boundary_chd_spd(model)
    idomain = np.ones((1, 6), dtype=int)
    idomain[0, [0, 3]] = 0  # the two west cells

    refuse_constant_heads_below_bottom(
        model,
        botm=np.zeros((1, 6), dtype=float),
        idomain=idomain,
        ocean_spd={},
        stream_spd={},
        side_spd=side,
    )


def test_a_stream_head_overwritten_by_a_side_head_is_not_checked() -> None:
    model = _side_model_with_heads(west=5.0, east=5.0)
    side = build_side_boundary_chd_spd(model)
    # The stream claims the west cell 0 with a head below the bottom, and the
    # side writes over it: MODFLOW 6 receives the side head only.
    stream = {0: [[0, 0, -1.0]], 1: [[0, 0, -1.0]]}

    refuse_constant_heads_below_bottom(
        model,
        botm=np.zeros((1, 6), dtype=float),
        idomain=np.ones((1, 6), dtype=int),
        ocean_spd={},
        stream_spd=stream,
        side_spd=side,
    )

    stream = {0: [[0, 1, -1.0]], 1: [[0, 1, -1.0]]}
    with pytest.raises(SolverInputError, match=r"flow\.bc\.stream: 1 cell\(s\): layer 0 cell 1"):
        refuse_constant_heads_below_bottom(
            model,
            botm=np.zeros((1, 6), dtype=float),
            idomain=np.ones((1, 6), dtype=int),
            ocean_spd={},
            stream_spd=stream,
            side_spd=side,
        )


def test_modflow6_reads_a_boundary_group_by_its_family_name_or_its_bare_name() -> None:
    labels = {1: "east_custom"}
    for support_label in ("east_custom", "boundary:east_custom"):
        model = _build_unstructured_model(boundary_labels_by_edge_id=labels)
        model.flow = SimpleNamespace(
            boundary_conditions={
                "east_side": SimpleNamespace(value=6.0, units="m", support_label=support_label)
            },
            active_bc=["east_side"],
        )

        assert build_side_boundary_chd_spd(model)[0] == [[0, 0, pytest.approx(6.0)]]


def test_modflow6_refuses_a_support_label_that_matches_no_cell() -> None:
    model = _build_unstructured_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "east_side": SimpleNamespace(value=6.0, units="m", support_label="nowhere")
        },
        active_bc=["east_side"],
    )

    with pytest.raises(ValueError, match="support_label='nowhere' did not match"):
        build_side_boundary_chd_spd(model)


def test_modflow6_applies_a_support_label_on_a_regular_grid() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=3.0, units="m", support_label="boundary:south")
        },
        active_bc=["west_side"],
    )

    # The label wins over the side the boundary is named after: the south row of 2 x 3.
    assert [row[1] for row in build_side_boundary_chd_spd(model)[0]] == [3, 4, 5]


def test_modflow6_builds_a_stream_chd_on_the_river_chain_of_a_regular_grid() -> None:
    model = _build_model()
    model.solver_mesh = regular_solver_mesh(2, 3, river=LineString([(0.5, 1.5), (1.5, 0.5)]))
    model.flow = SimpleNamespace(
        boundary_conditions={"stream": SimpleNamespace(value=7.0)},
        active_bc=["stream"],
    )

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

    chain_cells = np.concatenate(
        [chain.cell_ids for chain in model.solver_mesh.cell_mesh.chains("rivers")]
    )
    assert np.flatnonzero(stream_mask).tolist() == sorted(set(chain_cells.tolist()))
    assert stream_mask.sum() >= 2
    assert [row[1] for row in chd_spd[0]] == np.flatnonzero(stream_mask).tolist()


def test_modflow6_refuses_a_stream_chd_on_a_mesh_without_river_cells() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={"stream": SimpleNamespace(value=7.0)},
        active_bc=["stream"],
    )

    with pytest.raises(ValueError, match="selected runtime mesh support is empty"):
        build_stream_boundary_chd_spd(model)


def test_modflow6_cannot_pick_boundary_cells_without_a_solver_mesh() -> None:
    model = _build_model()
    model.solver_mesh = None
    model.flow = SimpleNamespace(
        boundary_conditions={"west_side": SimpleNamespace(value=1.0)},
        active_bc=["west_side"],
    )

    with pytest.raises(ValueError, match="reads the cells of the solver mesh"):
        build_side_boundary_chd_spd(model)


def test_a_constant_head_is_written_only_on_the_active_cells_of_its_column() -> None:
    model = _side_model_with_heads(west=8.0, east=8.0)
    base = model.solver_mesh
    idomain = np.ones((2, 6), dtype=int)
    idomain[0, 0] = 0  # the top cell of the first west column is inactive
    idomain[1, 3] = -1  # the lower cell of the second west column is a pass-through
    model.solver_mesh = SolverMesh(
        cell_mesh=base.cell_mesh,
        top=base.top,
        botm=np.vstack([base.top - 4.0, base.top - 9.0]),
        idomain=idomain,
    )
    model.nlay = 2

    rows = build_side_boundary_chd_spd(model)[0]

    west = sorted((row[0], row[1]) for row in rows if row[1] in (0, 3))
    assert west == [(0, 3), (1, 0)]
