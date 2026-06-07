from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.physics.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.physics.flow.initial_conditions import FlowICCustom, FlowInitialConditions
from hydromodpy.solver.modflow6.builders import (
    apply_side_boundary_start_heads,
    build_side_boundary_chd_spd,
    build_start_heads,
    build_stream_boundary_chd_spd,
)

from ._test_modflow6_boundary_conditions_builders import (
    _build_model,
    _build_unstructured_model,
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
