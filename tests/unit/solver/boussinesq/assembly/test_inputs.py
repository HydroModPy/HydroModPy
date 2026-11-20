"""Normalization of cell, edge and head inputs of the Boussinesq assembly.

Heads are in m. A missing input becomes zeros on cells and NaN on edges and on imposed heads.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.assembly.inputs import (
    as_cell_vector,
    as_edge_vector,
    as_prescribed_head_cell_vector,
    resolve_boundary_head_inputs,
)
from tests._helpers.boussinesq_mesh_doubles import line_mesh

MESH = line_mesh([0.0, 0.0, 0.0])

CELL_VECTORS = [
    pytest.param(None, [0.0, 0.0, 0.0], id="missing"),
    pytest.param([], [0.0, 0.0, 0.0], id="empty"),
    pytest.param(2.5, [2.5, 2.5, 2.5], id="scalar"),
    pytest.param([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], id="one per cell"),
]


@pytest.mark.parametrize(("values", "expected"), CELL_VECTORS)
def test_cell_vector(values, expected) -> None:
    np.testing.assert_array_equal(as_cell_vector(values, n_cells=3, label="recharge"), expected)


def test_missing_heads_are_nan() -> None:
    assert np.isnan(as_prescribed_head_cell_vector(None, n_cells=3, label="h")).all()
    assert np.isnan(as_edge_vector(None, n_edges=2, label="h")).all()


def test_head_inputs_of_two_edges_and_no_cell() -> None:
    inputs = resolve_boundary_head_inputs(
        MESH,
        head_m=np.asarray([1.0, 2.0, 3.0]),
        boundary_head_m_by_edge=np.asarray([4.0, np.nan]),
        prescribed_head_m_by_cell=None,
    )

    np.testing.assert_array_equal(inputs.head_m, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(inputs.boundary_head_m_by_edge, [4.0, np.nan])
    assert not inputs.prescribed_mask.any()


REFUSALS = [
    pytest.param(
        as_cell_vector,
        {"values": [1.0, 2.0], "n_cells": 3, "label": "recharge"},
        "recharge must be scalar or have length 3; got 2",
        id="cell vector size",
    ),
    pytest.param(
        as_prescribed_head_cell_vector,
        {"values": [1.0], "n_cells": 3, "label": "cell heads"},
        "cell heads must have length 3; got 1",
        id="cell head size",
    ),
    pytest.param(
        as_edge_vector,
        {"values": [1.0], "n_edges": 2, "label": "edge heads"},
        "edge heads must have length 2; got 1",
        id="edge head size",
    ),
    pytest.param(
        resolve_boundary_head_inputs,
        {"mesh": MESH, "head_m": np.zeros(2), "prescribed_head_m_by_cell": None},
        r"head_m length must match mesh.n_cells \(2 != 3\)",
        id="head size",
    ),
    pytest.param(
        resolve_boundary_head_inputs,
        {
            "mesh": MESH,
            "head_m": np.zeros(3),
            "boundary_head_m_by_edge": np.asarray([1.0, np.nan]),
            "prescribed_head_m_by_cell": np.asarray([1.0, np.nan, np.nan]),
        },
        "mutually exclusive",
        id="edge and cell heads together",
    ),
]


@pytest.mark.parametrize(("function", "kwargs", "message"), REFUSALS)
def test_refusals(function, kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        function(**kwargs)
