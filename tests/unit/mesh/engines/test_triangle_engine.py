"""The triangle engine embeds its lines, keeps each row's left cell on the left and reads a .msh."""

from __future__ import annotations

import dataclasses
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.engines.triangle.engine import (
    TriangleMeshEngine,
    triangulate_request,
)
from hydromodpy.spatial.mesh.engines.triangle.gmsh_cdt import MESH_SIZE_PER_CELL_SIZE, triangulate
from hydromodpy.spatial.mesh.gmsh_grid.exchange_api import load_planar_mesh
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import read_gmsh_2d_mesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh
from hydromodpy.spatial.mesh.request import (
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
    SizeField,
)

WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 350_000.0, 6_780_000.0
"""A Lambert-93 origin, so the driver's shift to a kilometre origin is exercised."""
BUNDLES = Path(__file__).resolve().parents[4] / "validation_cases" / "shared" / "mesh_bundles"
ISLAND_BUNDLE = BUNDLES / "dupuit_circular_island_ocean_irregular_tri_radial_48"
GRADED_BUNDLE = BUNDLES / "stream_depletion_glover_balmer_tri_refined_well"

needs_gmsh = pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")

RIVER = LineString([(X0 + 100, Y0 + 150), (X0 + 450, Y0 + 420), (X0 + 900, Y0 + 880)])
CONTACT = LineString([(X0 + 400, Y0), (X0 + 600, Y0 + 1000)])
BENT_CONTACT = LineString([(X0 + 400, Y0), (X0 + 530, Y0 + 500), (X0 + 600, Y0 + 1000)])


def _grid(xmin: float, ymin: float, xmax: float, ymax: float, n: int = 10) -> RasterGridSpec:
    return RasterGridSpec(
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        dx=(xmax - xmin) / n,
        dy=(ymax - ymin) / n,
        nrow=n,
        ncol=n,
        crs_wkt=WKT,
    )


def _square(*, lines=None, domain: Polygon | None = None, **options) -> MeshRequest:
    domain = box(X0, Y0, X0 + 1000, Y0 + 1000) if domain is None else domain
    return MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=_grid(*domain.bounds),
        nominal_size_m=50.0,
        lines=(
            (
                LineFamilySpec("rivers", "cell", (RIVER,)),
                LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)),
            )
            if lines is None
            else lines
        ),
        options=options,
    )


def _sized_square(size: float) -> MeshRequest:
    """The square as the planner hands it: a uniform size field, lines cut every *size*."""
    request = _square(
        lines=(
            LineFamilySpec("rivers", "cell", (shapely.segmentize(RIVER, size),)),
            LineFamilySpec(
                "geology",
                "face",
                (shapely.segmentize(BENT_CONTACT, size),),
                ("west_unit",),
                ("east_unit",),
            ),
        )
    )
    grid = _grid(X0, Y0, X0 + 1000, Y0 + 1000, n=40)
    field = SizeField(np.full((grid.nrow, grid.ncol), size), grid)
    return dataclasses.replace(request, nominal_size_m=size, size_field=field)


def _read_request(path: Path) -> MeshRequest:
    data = read_gmsh_2d_mesh(path)
    triangulation = InputTriangulation(data.points_xy, data.connectivity, {})
    mesh = HydroMesh(
        vertices=data.points_xy,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(data.connectivity)),),
    )
    domain = domain_polygon_from_mesh(mesh)
    return MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=_grid(*domain.bounds),
        nominal_size_m=10.0,
        input_triangulation=triangulation,
    )


def _rows(cell_mesh, family: str) -> np.ndarray:
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(family)
    return np.column_stack([table.node_a[rows], table.node_b[rows]])


def _side_of(cell_mesh, family: str, column: str) -> np.ndarray:
    """Cross product sign of each row's cell centre against the oriented row."""
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(family)
    cells = getattr(table, column)[rows]
    start = cell_mesh.mesh.vertices[table.node_a[rows]]
    tangent = cell_mesh.mesh.vertices[table.node_b[rows]] - start
    offset = cell_mesh.centers[np.maximum(cells, 0)] - start
    side = np.sign(tangent[:, 0] * offset[:, 1] - tangent[:, 1] * offset[:, 0])
    return np.where(cells >= 0, side, 0.0)


@needs_gmsh
def test_the_registry_serves_the_triangle_engine() -> None:
    assert type(registry.create("triangle")) is TriangleMeshEngine


@needs_gmsh
def test_each_family_row_has_its_first_cell_on_the_left_of_the_line() -> None:
    cell_mesh = TriangleMeshEngine().build(_square())

    for family in ("rivers", "geology"):
        assert np.all(_side_of(cell_mesh, family, "cell_a") > 0), family
        assert np.all(_side_of(cell_mesh, family, "cell_b") < 0), family


@needs_gmsh
def test_the_rows_of_a_line_run_along_it_end_to_end() -> None:
    cell_mesh = TriangleMeshEngine().build(_square())
    vertices = cell_mesh.mesh.vertices
    rows = _rows(cell_mesh, "geology")

    assert np.array_equal(rows[1:, 0], rows[:-1, 1])
    assert np.allclose(vertices[rows[0, 0]], CONTACT.coords[0], atol=1e-6)
    assert np.allclose(vertices[rows[-1, 1]], CONTACT.coords[-1], atol=1e-6)
    quality = cell_mesh.qa.families["geology"]
    assert quality["hausdorff_m"] <= 1e-6
    assert quality["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)


@needs_gmsh
def test_a_cell_takes_the_zone_of_its_side_of_the_contact() -> None:
    cell_mesh = TriangleMeshEngine().build(_square())
    x, y = cell_mesh.centers.T
    # The contact runs from (400, 0) to (600, 1000): x = 400 + 0.2 y.
    west = x < X0 + 400 + 0.2 * (y - Y0)
    zones = np.asarray(cell_mesh.zone_names)[cell_mesh.cell_zone]

    assert set(cell_mesh.zone_names) == {"west_unit", "east_unit"}
    assert np.all(zones[west] == "west_unit")
    assert np.all(zones[~west] == "east_unit")


@needs_gmsh
def test_a_river_chain_steps_from_face_to_face_on_one_bank() -> None:
    cell_mesh = TriangleMeshEngine().build(_square())
    (chain,) = cell_mesh.chains("rivers")

    for first, second in zip(chain.cell_ids[:-1], chain.cell_ids[1:], strict=True):
        assert second in cell_mesh.geometry.neighbours(first)
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0
    river_cells = set(cell_mesh.face_families.cell_a[cell_mesh.face_rows("rivers")].tolist())
    assert river_cells <= set(chain.cell_ids.tolist())


@needs_gmsh
def test_the_box_sides_are_boundary_families_without_a_second_cell() -> None:
    cell_mesh = TriangleMeshEngine().build(_square())
    table = cell_mesh.face_families

    for side in ("west", "east", "south", "north"):
        rows = cell_mesh.face_rows(f"boundary:{side}")
        assert np.all(table.cell_b[rows] == -1)
        assert cell_mesh.qa.families[f"boundary:{side}"]["length_m"] == pytest.approx(1000.0)


@needs_gmsh
def test_the_identity_names_the_engine_the_request_and_its_seed() -> None:
    request = _square()
    cell_mesh = TriangleMeshEngine().build(request)

    assert cell_mesh.identity.engine_id == "triangle"
    assert cell_mesh.identity.request_hash == request.canonical_hash()
    assert cell_mesh.identity.seed == request.seed
    assert cell_mesh.qa.declarations == TriangleMeshEngine.capabilities.declarations()
    assert cell_mesh.crs_wkt == WKT
    assert cell_mesh.qa.area_sum_rel_error <= 1e-9


@needs_gmsh
def test_a_hole_in_the_domain_stays_empty() -> None:
    hole = box(X0 + 300, Y0 + 300, X0 + 500, Y0 + 500)
    domain = box(X0, Y0, X0 + 1000, Y0 + 1000).difference(hole)
    river = LineString([(X0 + 700, Y0), (X0 + 700, Y0 + 1000)])
    cell_mesh = TriangleMeshEngine().build(
        _square(domain=domain, lines=(LineFamilySpec("rivers", "cell", (river,)),))
    )

    assert cell_mesh.qa.area_sum_m2 == pytest.approx(domain.area, rel=1e-9)
    assert not shapely.contains_xy(hole, *cell_mesh.centers.T).any()
    assert cell_mesh.chains("rivers")


@needs_gmsh
def test_a_line_that_leaves_the_domain_is_refused() -> None:
    outside = LineString([(X0 + 500, Y0 + 500), (X0 + 1500, Y0 + 500)])
    request = _square(lines=(LineFamilySpec("rivers", "cell", (outside,)),))

    with pytest.raises(MeshRequestError, match="leaves the mesh domain"):
        TriangleMeshEngine().build(request)


@needs_gmsh
def test_an_unknown_algorithm_is_refused() -> None:
    with pytest.raises(MeshRequestError, match="unknown triangle algorithm"):
        TriangleMeshEngine().build(_square(algorithm="bowyer"))


@needs_gmsh
def test_the_gmsh_driver_returns_the_edges_of_each_line_in_line_order() -> None:
    result = triangulate(_square())
    edges = result.line_edges[("rivers", 0)]

    assert np.array_equal(edges[1:, 0], edges[:-1, 1])
    start = result.vertices[edges[:, 0]]
    stop = result.vertices[edges[:, 1]]
    along = shapely.line_locate_point(RIVER, shapely.points(0.5 * (start + stop)))
    assert np.all(np.diff(along) > 0.0)


@needs_gmsh
def test_a_sized_request_embeds_its_lines_at_the_edge_length_of_its_triangles() -> None:
    """A triangle of area h^2 has edges of about 1.6 h, along the lines as elsewhere."""
    size = 50.0
    result = triangulate(_sized_square(size))
    edge = MESH_SIZE_PER_CELL_SIZE["delaunay"] * size
    crossing = RIVER.project(RIVER.intersection(BENT_CONTACT))

    expected = round(crossing / edge) + round((RIVER.length - crossing) / edge)
    assert len(result.line_edges[("rivers", 0)]) == expected


@needs_gmsh
def test_the_faces_of_a_sized_request_follow_the_lines_its_triangles_embed() -> None:
    cell_mesh = TriangleMeshEngine().build(_sized_square(50.0))
    quality = cell_mesh.qa.families["geology"]

    assert quality["hausdorff_m"] <= 1e-6
    assert quality["covered_length_rel"] == pytest.approx(1.0, abs=1e-9)
    assert cell_mesh.qa.size_fidelity


def test_the_centres_are_the_vertex_means_of_the_planar_mesh_reader() -> None:
    for bundle in (ISLAND_BUNDLE, GRADED_BUNDLE):
        cell_mesh = TriangleMeshEngine().build(_read_request(bundle / "mesh_2d.msh"))
        x, y = load_planar_mesh(bundle / "mesh_2d.msh").cell_centroids()

        assert np.array_equal(cell_mesh.centers[:, 0], x)
        assert np.array_equal(cell_mesh.centers[:, 1], y)
        assert cell_mesh.identity.seed is None


def _three_zones() -> MeshRequest:
    """Zones a (north-west), b (north-east) and c (south), parted by three contacts."""
    contacts = (
        LineString([(X0 + 500, Y0 + 500), (X0 + 500, Y0 + 1000)]),
        LineString([(X0, Y0 + 500), (X0 + 500, Y0 + 500)]),
        LineString([(X0 + 500, Y0 + 500), (X0 + 1000, Y0 + 500)]),
    )
    return _square(
        lines=(
            LineFamilySpec("rivers", "cell", (RIVER,)),
            LineFamilySpec("geology", "face", contacts, ("a", "a", "b"), ("b", "c", "c")),
        )
    )


def _fed_back(request: MeshRequest, labels: bool) -> tuple[MeshRequest, object]:
    """The triangulation of *request* handed back as an input, with or without its groups."""
    triangulated = triangulate_request(request)
    generated = TriangleMeshEngine().assemble(triangulated)
    edge_labels = {}
    if labels:
        geology = triangulated.families.get("geology")
        pairs = np.column_stack([geology.node_a, geology.node_b])
        edge_labels = {
            "river::trace": _rows(generated, "rivers"),
            "interface::a::b": pairs[geology.line == 0],
            "interface::a::c": pairs[geology.line == 1],
            "interface::b::c": pairs[geology.line == 2],
        }
    triangulation = InputTriangulation(
        generated.mesh.vertices, np.asarray(generated.mesh.flat_connectivity), edge_labels
    )
    read = MeshRequest(
        domain=request.domain,
        crs_wkt=WKT,
        grid=request.grid,
        nominal_size_m=request.nominal_size_m,
        lines=() if labels else request.lines,
        input_triangulation=triangulation,
    )
    return read, generated


def _zone_of_cells(cell_mesh) -> np.ndarray:
    names = np.asarray(cell_mesh.zone_names + ("",))
    return names[np.where(cell_mesh.cell_zone >= 0, cell_mesh.cell_zone, len(names) - 1)]


@needs_gmsh
@pytest.mark.parametrize("labels", [True, False], ids=["physical_groups", "line_matching"])
def test_a_read_triangulation_finds_the_families_it_was_generated_with(labels: bool) -> None:
    read, generated = _fed_back(_three_zones(), labels)
    cell_mesh = TriangleMeshEngine().build(read)

    for family in ("rivers", "geology"):
        assert {tuple(sorted(r)) for r in _rows(cell_mesh, family).tolist()} == {
            tuple(sorted(r)) for r in _rows(generated, family).tolist()
        }, family
    assert set(_zone_of_cells(generated).tolist()) == {"a", "b", "c"}
    assert np.array_equal(_zone_of_cells(cell_mesh), _zone_of_cells(generated))
    assert cell_mesh.chains("rivers")
    assert "family lines were not embedded" in " ".join(cell_mesh.qa.notes)


@needs_gmsh
def test_one_interface_group_alone_does_not_say_which_zone_is_on_which_side() -> None:
    request = _square()
    triangulated = triangulate_request(request)
    geology = triangulated.families.get("geology")
    triangulation = InputTriangulation(
        triangulated.mesh.vertices,
        np.asarray(triangulated.mesh.flat_connectivity),
        {"interface::east_unit::west_unit": np.column_stack([geology.node_a, geology.node_b])},
    )
    read = MeshRequest(
        domain=request.domain,
        crs_wkt=WKT,
        grid=request.grid,
        nominal_size_m=request.nominal_size_m,
        input_triangulation=triangulation,
    )
    cell_mesh = TriangleMeshEngine().build(read)

    assert cell_mesh.face_rows("geology").any()
    assert np.all(cell_mesh.cell_zone == -1)
