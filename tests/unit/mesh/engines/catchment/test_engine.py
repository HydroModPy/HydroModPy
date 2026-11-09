"""The catchment engine: the catchment the outlet closes, as one polygon cell with no face.

Each outline gives one cell on its exterior ring, counterclockwise, of the area of
that ring, with its center inside. A hole is filled and noted. The cell is the
catchment and not the domain of the request. One cell holds no line, no grading
and no triangulation, so the engine refuses them by name.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.engines.catchment.engine import CatchmentMeshEngine
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.request import InputTriangulation, LineFamilySpec, MeshRequest
from tests._helpers.fake_engines import lumped_capabilities
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    LAMBERT93_WKT,
    grid_over,
    mesh_request,
    uniform_size_field,
)

pytestmark = pytest.mark.fast

X0, Y0 = L93_ORIGIN


def _square() -> Polygon:
    return box(X0, Y0, X0 + 2000.0, Y0 + 2000.0)


def _disk() -> Polygon:
    """A disk of 64 vertices."""
    return Point(X0 + 1000.0, Y0 + 1000.0).buffer(1000.0, quad_segs=16)


def _crescent() -> Polygon:
    """An annular sector of 300 degrees: its vertex mean lies outside it."""
    angles = np.radians(np.linspace(0.0, 300.0, 61))
    outer = np.column_stack([np.cos(angles), np.sin(angles)]) * 1000.0
    inner = np.column_stack([np.cos(angles), np.sin(angles)])[::-1] * 600.0
    return Polygon(np.vstack([outer, inner]) + (X0 + 1000.0, Y0 + 1000.0))


def _holed() -> Polygon:
    """A 2 km square with two holes of 100 m by 100 m."""
    holes = [
        box(X0 + 400.0, Y0 + 400.0, X0 + 500.0, Y0 + 500.0),
        box(X0 + 1400.0, Y0 + 1200.0, X0 + 1500.0, Y0 + 1300.0),
    ]
    return Polygon(_square().exterior, [hole.exterior.coords for hole in holes])


def _real_size_outline() -> Polygon:
    """A wavy outline of 1 256 vertices and about 60 km2, the size of a delineated catchment."""
    angles = np.linspace(0.0, 2.0 * np.pi, 1256, endpoint=False)
    radius = 4400.0 * (1.0 + 0.15 * np.sin(7.0 * angles) + 0.04 * np.sin(31.0 * angles))
    xy = np.column_stack([np.cos(angles), np.sin(angles)]) * radius[:, None]
    return Polygon(xy + (X0 + 6000.0, Y0 + 6000.0))


OUTLINES: dict[str, Callable[[], Polygon]] = {
    "square": _square,
    "disk_of_64_vertices": _disk,
    "crescent": _crescent,
    "two_holes": _holed,
    "outline_of_1256_vertices": _real_size_outline,
}


def _request(catchment: Polygon | None, **overrides: object) -> MeshRequest:
    """A request on a grid around *catchment*, whose domain is the box of that grid."""
    area = catchment if catchment is not None else _square()
    grid = grid_over(area.envelope.buffer(100.0, join_style="mitre"), crs_wkt=LAMBERT93_WKT)
    return mesh_request(grid, catchment=catchment, **overrides)


def _built(name: str) -> tuple[Polygon, MeshRequest, PlanarCellMesh]:
    catchment = OUTLINES[name]()
    request = _request(catchment)
    return catchment, request, CatchmentMeshEngine().build(request)


def test_the_engine_declares_a_lumped_polygon_engine() -> None:
    capabilities = CatchmentMeshEngine.capabilities

    # One cell holds no line, so the engine names every family it skips.
    ignored = frozenset({"rivers", "lakes", "barriers", "geology", "watershed_boundary"})
    assert capabilities == lumped_capabilities(ignored_families=ignored)
    assert (CatchmentMeshEngine.engine_id, CatchmentMeshEngine.engine_version) == ("catchment", "1")


@pytest.mark.parametrize("name", list(OUTLINES))
def test_an_outline_is_one_polygon_cell_with_no_face(name: str) -> None:
    catchment, request, cell_mesh = _built(name)

    assert cell_mesh.n_cells == 1
    assert cell_mesh.mesh.cell_types[0] is CellType.POLYGON
    assert cell_mesh.mesh.n_nodes == len(catchment.exterior.coords) - 1
    assert cell_mesh.face_families is None
    assert cell_mesh.cell_chains == ()
    assert cell_mesh.structured_shape is None
    assert cell_mesh.crs_wkt == request.crs_wkt


@pytest.mark.parametrize("name", list(OUTLINES))
def test_the_cell_has_the_area_of_the_exterior_ring(name: str) -> None:
    catchment, _, cell_mesh = _built(name)
    shell_m2 = Polygon(catchment.exterior).area

    assert float(cell_mesh.geometry.areas[0]) == pytest.approx(shell_m2, rel=1.0e-12)
    assert cell_mesh.qa.area_sum_m2 == pytest.approx(shell_m2, rel=1.0e-12)


@pytest.mark.parametrize("name", list(OUTLINES))
def test_the_ring_turns_counterclockwise(name: str) -> None:
    _, _, cell_mesh = _built(name)

    assert shapely.LinearRing(cell_mesh.mesh.vertices).is_ccw


@pytest.mark.parametrize("name", list(OUTLINES))
def test_the_center_is_an_interior_point_of_the_cell(name: str) -> None:
    _, _, cell_mesh = _built(name)
    (cell,) = cell_polygons(cell_mesh.mesh.vertices, cell_mesh.connectivity_rows)

    assert cell_mesh.center_kind == "interior_point"
    assert cell.contains(Point(cell_mesh.centers[0]))


def test_the_vertex_mean_of_a_crescent_lies_outside_it_and_the_center_inside() -> None:
    catchment, _, cell_mesh = _built("crescent")
    vertex_mean = np.asarray(catchment.exterior.coords)[:-1].mean(axis=0)

    assert not catchment.contains(Point(vertex_mean))
    assert catchment.contains(Point(cell_mesh.centers[0]))


def test_a_ring_drawn_clockwise_gives_the_same_cell() -> None:
    catchment = _crescent()
    clockwise = Polygon(list(catchment.exterior.coords)[::-1])

    drawn = CatchmentMeshEngine().build(_request(clockwise))
    reference = CatchmentMeshEngine().build(_request(catchment))

    assert shapely.normalize(Polygon(drawn.mesh.vertices)).equals_exact(
        shapely.normalize(Polygon(reference.mesh.vertices)), 0.0
    )
    np.testing.assert_array_equal(drawn.centers, reference.centers)


def test_the_holes_are_filled_and_noted() -> None:
    _, _, cell_mesh = _built("two_holes")

    assert cell_mesh.qa.notes == (
        "catchment fills 2 holes of the catchment outline, 20000 m2 in all: water that "
        "falls in a hole still reaches the outlet",
    )


@pytest.mark.parametrize("name", ["square", "crescent", "outline_of_1256_vertices"])
def test_an_outline_without_a_hole_gives_no_note(name: str) -> None:
    _, _, cell_mesh = _built(name)

    assert cell_mesh.qa.notes == ()


def test_a_repeated_vertex_does_not_repeat_in_the_cell() -> None:
    coords = list(_square().exterior.coords)
    repeated = Polygon([coords[0], coords[1], coords[1], coords[2], coords[3]])

    cell_mesh = CatchmentMeshEngine().build(_request(repeated))

    assert cell_mesh.mesh.n_nodes == 4
    assert cell_mesh.qa.n_duplicate_vertices_in_cells == 0


def test_the_cell_is_the_catchment_and_not_the_domain() -> None:
    """The domain of a real run may be the DEM rectangle; the cell is still the catchment."""
    catchment = _disk()
    request = _request(catchment)

    cell_mesh = CatchmentMeshEngine().build(request)

    assert request.domain.area > 1.2 * catchment.area
    assert float(cell_mesh.geometry.areas[0]) == pytest.approx(catchment.area, rel=1.0e-12)


def test_the_mesh_names_the_engine_and_its_request() -> None:
    _, request, cell_mesh = _built("disk_of_64_vertices")

    assert cell_mesh.identity.engine_id == "catchment"
    assert cell_mesh.identity.engine_version == "1"
    assert cell_mesh.identity.request_hash == request.canonical_hash()
    assert cell_mesh.identity.seed is None
    assert cell_mesh.qa.declarations == lumped_capabilities().declarations()


def test_two_builds_of_one_request_give_the_same_cell() -> None:
    request = _request(_real_size_outline())

    first = CatchmentMeshEngine().build(request)
    second = CatchmentMeshEngine().build(request)

    np.testing.assert_array_equal(first.mesh.vertices, second.mesh.vertices)
    np.testing.assert_array_equal(first.centers, second.centers)
    # One cell has no interior face, so its face statistics are NaN: compare NaN as equal.
    np.testing.assert_equal(first.qa.as_dict(), second.qa.as_dict())


def _triangulation() -> InputTriangulation:
    return InputTriangulation(
        vertices=np.array([[X0, Y0], [X0 + 2000.0, Y0], [X0 + 2000.0, Y0 + 2000.0]]),
        triangles=np.array([[0, 1, 2]]),
        edge_labels={},
    )


def _river() -> LineFamilySpec:
    return LineFamilySpec(
        "rivers", "cell", (LineString([(X0 + 100.0, Y0 + 100.0), (X0 + 1900.0, Y0 + 1900.0)]),)
    )


def _sized() -> MeshRequest:
    grid = grid_over(_square(), 100.0, crs_wkt=LAMBERT93_WKT)
    return mesh_request(grid, catchment=_square(), size_field=uniform_size_field(grid, 100.0))


REFUSALS: dict[str, tuple[Callable[[], MeshRequest], str]] = {
    "no catchment": (
        lambda: _request(None),
        r"meshes MeshRequest.catchment as one cell, and the request carries no catchment",
    ),
    "lines": (lambda: _request(_square(), lines=(_river(),)), r"refuses MeshRequest.lines$"),
    "size field": (_sized, r"refuses MeshRequest.size_field$"),
    "input triangulation": (
        lambda: _request(_square(), input_triangulation=_triangulation()),
        r"refuses MeshRequest.input_triangulation$",
    ),
    "lines and a triangulation": (
        lambda: _request(_square(), lines=(_river(),), input_triangulation=_triangulation()),
        r"refuses MeshRequest.lines, MeshRequest.input_triangulation$",
    ),
}


@pytest.mark.parametrize("case", list(REFUSALS))
def test_a_request_one_cell_cannot_hold_is_refused_by_name(case: str) -> None:
    build, message = REFUSALS[case]
    request = build()

    with pytest.raises(MeshRequestError, match=message):
        CatchmentMeshEngine().build(request)
