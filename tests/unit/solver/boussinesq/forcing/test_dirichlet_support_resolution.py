"""Edges and cells that carry a prescribed head: a side of the domain, the stream, or a named support.

A support is found by the label of the boundary condition, or by its side or the river tag of the
mesh. A support that matches no edge or no cell is refused, since the head would be applied nowhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from hydromodpy.solver.boussinesq.forcing.dirichlet_support_resolution import (
    DirichletSupportResolutionMixin,
)

NONE = np.array([], dtype=int)


@dataclass
class SupportMesh:
    """Which edges and cells of a small mesh carry each label or side."""

    edges: dict[str, np.ndarray] = field(default_factory=dict)
    cells: dict[str, np.ndarray] = field(default_factory=dict)

    def edge_indices_for_label(self, label: str) -> np.ndarray:
        return self.edges.get(label, NONE)

    def cell_indices_for_label(self, label: str) -> np.ndarray:
        return self.cells.get(label, NONE)

    def boundary_edge_indices_for_side(self, side: str) -> np.ndarray:
        return self.edges.get(f"side:{side}", NONE)

    def boundary_cell_indices_for_side(self, side: str) -> np.ndarray:
        return self.cells.get(f"side:{side}", NONE)


class Host(ForcingCommonMixin, DirichletSupportResolutionMixin):
    def __init__(self, mesh: SupportMesh) -> None:
        self.mesh = mesh


def west_and_creek() -> Host:
    return Host(
        SupportMesh(
            edges={
                "side:west": np.array([0, 1]),
                "stream": np.array([4]),
                "west_shore": np.array([2]),
                "creek": np.array([5, 6]),
                "edges_only": np.array([3]),
            },
            cells={
                "side:west": np.array([0]),
                "stream": np.array([4, 5]),
                "west_shore": np.array([1]),
                "creek": np.array([6]),
            },
        )
    )


def side(host: Host, boundary: object):
    return host.resolve_side_dirichlet_support(boundary=boundary, bc_id="west")


def stream(host: Host, boundary: object):
    return host.resolve_stream_dirichlet_support(boundary=boundary)


SUPPORTS = [
    pytest.param(side, SimpleNamespace(), "flow.bc.west", [0, 1], [0], id="side"),
    pytest.param(
        side,
        {"support_label": " west_shore "},
        "flow.bc.west [west_shore]",
        [2],
        [1],
        id="labelled side",
    ),
    pytest.param(stream, SimpleNamespace(), "flow.bc.stream", [4], [4, 5], id="stream"),
    pytest.param(
        stream,
        SimpleNamespace(support_label="creek"),
        "flow.bc.stream [creek]",
        [5, 6],
        [6],
        id="labelled stream",
    ),
]


@pytest.mark.parametrize(("resolve", "boundary", "label", "edges", "cells"), SUPPORTS)
def test_support_of_a_boundary(resolve, boundary, label: str, edges: list, cells: list) -> None:
    found_label, found_edges, found_cells = resolve(west_and_creek(), boundary)

    assert found_label == label
    np.testing.assert_array_equal(found_edges, edges)
    np.testing.assert_array_equal(found_cells, cells)


def declared(host: Host, boundary_conditions: dict):
    return host.require_active_dirichlet_boundary(
        boundary_conditions=boundary_conditions, bc_id="west"
    )


NO_BOUNDARY = SimpleNamespace()
EDGE = np.array([4])

REFUSALS = [
    pytest.param(
        side,
        SupportMesh(edges={"west_shore": np.array([2])}),
        {"support_label": "west_shore"},
        "support_label='west_shore' did not match any runtime mesh support",
        id="label with no cell",
    ),
    pytest.param(
        side,
        SupportMesh(cells={"side:west": np.array([0])}),
        NO_BOUNDARY,
        "Boundary 'west' is active but no matching boundary edge",
        id="side with no edge",
    ),
    pytest.param(
        side,
        SupportMesh(edges={"side:west": np.array([0])}),
        NO_BOUNDARY,
        "Boundary 'west' is active but no matching boundary cell",
        id="side with no cell",
    ),
    pytest.param(
        stream,
        SupportMesh(cells={"stream": EDGE}),
        NO_BOUNDARY,
        "no edge is tagged is_river",
        id="stream with no edge",
    ),
    pytest.param(
        stream,
        SupportMesh(edges={"stream": EDGE}),
        NO_BOUNDARY,
        "no cell is tagged by river support",
        id="stream with no cell",
    ),
    pytest.param(
        declared,
        SupportMesh(),
        {},
        "Active boundary 'west' is missing from flow.bc",
        id="boundary not declared",
    ),
    pytest.param(
        declared,
        SupportMesh(),
        {"west": SimpleNamespace(kind="Neumann")},
        "Boundary 'west' must be Dirichlet",
        id="not a head boundary",
    ),
]


@pytest.mark.parametrize(("resolve", "mesh", "boundary", "message"), REFUSALS)
def test_refusals(resolve, mesh: SupportMesh, boundary: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        resolve(Host(mesh), boundary)
