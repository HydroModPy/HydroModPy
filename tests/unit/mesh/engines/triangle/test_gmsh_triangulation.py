"""The gmsh constrained Delaunay driver: lines embedded as edges, sizes handed to gmsh, refusals."""

from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from hydromodpy.core.exceptions import MeshError, MeshRequestError
from hydromodpy.mesh.engines.triangle import gmsh_triangulation
from hydromodpy.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.mesh.engines.triangle.gmsh_triangulation import triangulate
from hydromodpy.mesh.request import LineFamilySpec, MeshRequest, SizeField
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    grid_over,
    grid_spec,
    mesh_request,
    square_domain,
    uniform_size_field,
)

needs_gmsh = pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")

X0, Y0 = L93_ORIGIN
"""A Lambert-93 origin, so the driver's shift to a kilometer origin is exercised."""
SQUARE = square_domain(1000.0, x0=X0, y0=Y0)
RIVER = LineString([(X0 + 100, Y0 + 150), (X0 + 450, Y0 + 420), (X0 + 900, Y0 + 880)])
CONTACT = LineString([(X0 + 400, Y0), (X0 + 600, Y0 + 1000)])
BENT_CONTACT = LineString([(X0 + 400, Y0), (X0 + 530, Y0 + 500), (X0 + 600, Y0 + 1000)])


def _square(*lines: LineFamilySpec, **options: object) -> MeshRequest:
    """The 1 km square at 50 m, by default with a river crossing a contact."""
    if not lines:
        lines = (
            LineFamilySpec("rivers", "cell", (RIVER,)),
            LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)),
        )
    return mesh_request(grid_over(SQUARE, 100.0), nominal_size_m=50.0, lines=lines, options=options)


def _sized_square(size: float) -> MeshRequest:
    """The square as the planner hands it: a uniform size field, lines cut every *size*."""
    grid = grid_over(SQUARE, 25.0)
    return mesh_request(
        grid,
        nominal_size_m=size,
        size_field=uniform_size_field(grid, size),
        lines=(
            LineFamilySpec("rivers", "cell", (shapely.segmentize(RIVER, size),)),
            LineFamilySpec(
                "geology",
                "face",
                (shapely.segmentize(BENT_CONTACT, size),),
                ("west_unit",),
                ("east_unit",),
            ),
        ),
    )


# --------------------------------------------------------------------------- #
# Lines embedded as mesh edges
# --------------------------------------------------------------------------- #


@needs_gmsh
def test_the_faces_of_a_sized_request_follow_the_lines_its_triangles_embed() -> None:
    cell_mesh = TriangleMeshEngine().build(_sized_square(50.0))
    quality = cell_mesh.qa.families["geology"]

    assert quality["hausdorff_m"] <= 1e-6
    assert quality["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)


@needs_gmsh
def test_two_line_vertices_closer_than_a_millimetre_are_one_vertex() -> None:
    """A digitizing double click leaves no edge of zero length along the river."""
    doubled = LineString(
        [
            (X0 + 100, Y0 + 150),
            (X0 + 450, Y0 + 420),
            (X0 + 450.0004, Y0 + 420.0002),
            (X0 + 900, Y0 + 880),
        ]
    )
    result = triangulate(_square(LineFamilySpec("rivers", "cell", (doubled,))))
    edges = result.line_edges[("rivers", 0)]
    lengths = np.linalg.norm(result.vertices[edges[:, 1]] - result.vertices[edges[:, 0]], axis=1)

    assert np.all(edges[:, 0] != edges[:, 1])
    assert lengths.min() > 1.0e-3


@needs_gmsh
@pytest.mark.parametrize("downstream", [True, False], ids=["with_the_contact", "against_it"])
def test_a_river_that_follows_a_contact_shares_its_edges(downstream: bool) -> None:
    """The river runs on the contact x = 500 m from y = 300 m to y = 700 m."""
    contact = LineString([(X0 + 500, Y0), (X0 + 500, Y0 + 1000)])
    river = LineString(
        [(X0 + 200, Y0 + 100), (X0 + 500, Y0 + 300), (X0 + 500, Y0 + 700), (X0 + 800, Y0 + 900)]
    )
    river = river if downstream else river.reverse()
    result = triangulate(
        _square(
            LineFamilySpec("rivers", "cell", (river,)),
            LineFamilySpec("geology", "face", (contact,), ("west_unit",), ("east_unit",)),
        )
    )
    vertices = result.vertices

    def along_the_contact(edges: np.ndarray) -> set[tuple[int, int]]:
        x = vertices[edges][:, :, 0]
        y = vertices[edges][:, :, 1]
        on = np.all(x == X0 + 500, axis=1) & np.all((y >= Y0 + 300) & (y <= Y0 + 700), axis=1)
        return {tuple(sorted(edge)) for edge in edges[on].tolist()}

    river_edges = result.line_edges[("rivers", 0)]
    shared = along_the_contact(river_edges)
    assert shared
    assert shared == along_the_contact(result.line_edges[("geology", 0)])
    along = shapely.line_locate_point(river, shapely.points(vertices[river_edges].mean(axis=1)))
    assert np.all(np.diff(along) > 0.0)


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


@needs_gmsh
@pytest.mark.parametrize(
    ("request_of", "message"),
    [
        (
            lambda: _square(
                LineFamilySpec(
                    "rivers", "cell", (LineString([(X0 + 500, Y0 + 500), (X0 + 1500, Y0 + 500)]),)
                )
            ),
            "line 0 of family 'rivers' leaves the mesh domain",
        ),
        (
            lambda: _square(
                LineFamilySpec(
                    "rivers",
                    "cell",
                    (LineString([(X0 + 500, Y0 + 500), (X0 + 500.0004, Y0 + 500)]),),
                )
            ),
            "line 0 of family 'rivers' is shorter than 1 mm",
        ),
    ],
    ids=["line_out_of_the_domain", "line_shorter_than_a_millimetre"],
)
def test_a_request_gmsh_cannot_triangulate_is_refused(request_of, message: str) -> None:
    with pytest.raises(MeshRequestError, match=message):
        TriangleMeshEngine().build(request_of())


def test_without_gmsh_the_engine_says_to_install_the_mesh_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "gmsh", None)

    with pytest.raises(MeshError, match="install the 'mesh' extra"):
        triangulate(_square())


# --------------------------------------------------------------------------- #
# The size field handed to gmsh
# --------------------------------------------------------------------------- #


class _FieldApi:
    """What gmsh is told about its background field."""

    def __init__(self) -> None:
        self.settings: dict[str, object] = {}
        self.background: int | None = None

    def add(self, kind: str) -> int:
        self.settings["kind"] = kind
        return 1

    def setString(self, tag: int, name: str, value: str) -> None:  # noqa: N802
        self.settings[name] = value

    def setNumber(self, tag: int, name: str, value: float) -> None:  # noqa: N802
        self.settings[name] = value

    def setAsBackgroundMesh(self, tag: int) -> None:  # noqa: N802
        self.background = tag


def _handed_to_gmsh(
    field: SizeField, scale: float, origin: np.ndarray, scratch: Path
) -> tuple[list[list[float]], np.ndarray, _FieldApi]:
    """The three header lines and the node values of the structured field gmsh reads."""
    api = _FieldApi()
    gmsh = SimpleNamespace(model=SimpleNamespace(mesh=SimpleNamespace(field=api)))
    gmsh_triangulation._write_size_field(gmsh, field, scale, origin, scratch)
    lines = Path(api.settings["FileName"]).read_text(encoding="utf-8").splitlines()
    header = [[float(token) for token in line.split()] for line in lines[:3]]
    return header, np.loadtxt(lines[3:], ndmin=2), api


def test_a_size_field_too_large_for_gmsh_keeps_the_finest_size_of_each_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Five rows and three columns over two nodes at most: blocks of 3 x 3 pixels, the last one cut."""
    monkeypatch.setattr(gmsh_triangulation, "_MAX_FIELD_NODES", 2)
    grid = grid_spec(5, 3, 10.0, xmin=X0, ymin=Y0)
    values = np.full((5, 3), 100.0)
    values[1, 2] = 20.0
    values[4, 0] = 30.0
    origin = np.array([X0, Y0])

    header, nodes, _ = _handed_to_gmsh(SizeField(values, grid), 1.0, origin, tmp_path)

    factor = 3
    assert header[1][:2] == [factor * grid.dx, factor * grid.dy]
    assert header[2][:2] == [1.0, 2.0]
    assert header[0][0] == 0.5 * factor * grid.dx
    assert header[0][1] == grid.ymax - (2 - 0.5) * factor * grid.dy - origin[1]
    np.testing.assert_array_equal(nodes, [[30.0, 20.0]])
