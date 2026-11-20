"""Families of the dual of a triangulation read from a file: river chains and contact staircases.

The triangulation is drawn by hand: a river edge 10 m long with two vertices one
meter off its middle, on both sides. The triangulation is not Delaunay there, so
the Voronoi cells of the two river vertices do not touch.
"""

from __future__ import annotations

import functools

import numpy as np
from shapely.geometry import LineString, box

from hydromodpy.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.request import InputTriangulation, LineFamilySpec
from tests._helpers.mesh_cases import L93_ORIGIN, grid_over, mesh_request

X0, Y0 = L93_ORIGIN
DOMAIN = box(X0, Y0, X0 + 30.0, Y0 + 20.0)
UPSTREAM, DOWNSTREAM, NORTH, SOUTH = 4, 5, 6, 7
"""The two river vertices and the two vertices that squeeze between their cells."""

VERTICES = np.array(
    [(0, 0), (30, 0), (30, 20), (0, 20), (10, 10), (20, 10), (15, 11), (15, 9)], dtype=float
) + (X0, Y0)
TRIANGLES = np.array(
    [
        (UPSTREAM, DOWNSTREAM, NORTH),
        (UPSTREAM, SOUTH, DOWNSTREAM),
        (UPSTREAM, NORTH, 3),
        (NORTH, 2, 3),
        (NORTH, DOWNSTREAM, 2),
        (0, UPSTREAM, 3),
        (DOWNSTREAM, 1, 2),
        (0, SOUTH, UPSTREAM),
        (0, 1, SOUTH),
        (SOUTH, 1, DOWNSTREAM),
    ]
)


@functools.cache
def squeezed_river() -> PlanarCellMesh:
    """The dual of the hand triangulation, its river on one edge, a contact on another."""
    triangulation = InputTriangulation(
        vertices=VERTICES,
        triangles=TRIANGLES,
        edge_labels={
            "river::0": np.array([[UPSTREAM, DOWNSTREAM]]),
            "interface::west::east": np.array([[UPSTREAM, NORTH]]),
        },
    )
    request = mesh_request(
        grid_over(DOMAIN, 1.0),
        domain=DOMAIN,
        nominal_size_m=10.0,
        input_triangulation=triangulation,
    )
    return VoronoiMeshEngine().build(request)


def test_squeezed_river_is_bridged() -> None:
    cell_mesh = squeezed_river()
    (chain,) = cell_mesh.chains("rivers")
    neighbours = cell_mesh.geometry.neighbours

    assert UPSTREAM not in neighbours(DOWNSTREAM)
    assert chain.cell_ids[[0, -1]].tolist() == [UPSTREAM, DOWNSTREAM]
    assert chain.cell_ids.size == 3
    assert chain.cell_ids[1] in (NORTH, SOUTH)
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0


def test_contact_edge_without_triangle() -> None:
    names = squeezed_river().face_families.names
    assert all(name == "rivers" or name.startswith("boundary:") for name in names)


def test_river_line_without_a_triangle_edge_gives_no_chain() -> None:
    # The line runs inside one triangle, so it matches no triangle edge.
    inside_a_triangle = LineString([(X0 + 2.0, Y0 + 14.0), (X0 + 6.0, Y0 + 16.0)])
    request = mesh_request(
        grid_over(DOMAIN, 1.0),
        domain=DOMAIN,
        nominal_size_m=10.0,
        input_triangulation=InputTriangulation(
            vertices=VERTICES, triangles=TRIANGLES, edge_labels={}
        ),
        lines=(LineFamilySpec("rivers", "cell", (inside_a_triangle,)),),
    )

    cell_mesh = VoronoiMeshEngine().build(request)

    assert cell_mesh.chains("rivers") == ()
    assert "rivers" not in cell_mesh.face_families.names
