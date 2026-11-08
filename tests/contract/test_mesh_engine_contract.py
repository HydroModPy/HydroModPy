"""Conformance suite for the mesh port, run against every engine.

Almost every assertion takes the ``engine`` fixture, and that fixture is
parametrized over what :mod:`hydromodpy.mesh.registry` resolves, not over
a list this file keeps. An engine installed beside this build is therefore run
by this suite without a line of ``tests/`` naming it. ``register()`` certifies a
class on the members it declares; the invariants a solver relies on (cells cover
their centers, the areas add up, a chain is continuous) are only visible on a
mesh, and this file is where they are checked. It is the one home of the
properties the three built-in engines share.

The cases are field situations every engine can take: a square catchment whose
river crosses a geological contact, the same catchment with every line drawn the
other way, a square with a hole, a circular island, a size ramp, a uniform size
and a given triangulation. On each the answer is known (the area, the side a
cell lies on, the line a face family must follow, the direction of a size ramp),
so the assertions are exact rather than banded. Each invariant is a short
function named after what it checks. Invariants are conditioned on what the
engine declares in its capabilities: a structured engine covers the DEM
rectangle, a graded engine follows a size ramp, an engine with exact faces
follows its face lines to ``HAUSDORFF_RTOL`` of the extent and orients its rows,
a deterministic engine builds the same mesh twice. Each mesh is built once per
engine and per case, and every test of that pair reads the same mesh.

A built-in engine this environment cannot run is skipped, unless
``HMP_REQUIRE_GMSH`` is set (CI with the ``mesh`` extra, a developer machine):
a green run that skipped two of the three engines proves nothing there. A
missing engine gives skipped tests, never fewer collected tests.
"""

from __future__ import annotations

import functools
import os
import random
import time
from collections.abc import Callable
from importlib.util import find_spec

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.core.plugin_registry import PluginRegistry
from hydromodpy.mesh import registry
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.planar.quality import DECLARATION_KEYS
from hydromodpy.mesh.port import MeshEngine, MeshEngineCapabilities, missing_engine_members
from hydromodpy.mesh.request import InputTriangulation, LineFamilySpec, MeshRequest, SizeField
from tests._helpers.mesh_cases import (
    LAMBERT93_WKT,
    grid_over,
    mesh_request,
    square_domain,
    uniform_size_field,
)
from tests._helpers.tolerances import tol

AREA_RTOL = tol("mesh_engine_conformance__sum_of_the_cell_areas_against_the_area_to_cover_relative")
HAUSDORFF_RTOL = tol(
    "mesh_engine_conformance__exact_faces_to_their_source_lines_"
    "hausdorff_distance_as_a_share_of_the_extent"
)
BUDGET_S = tol("mesh_engine_conformance__wall_clock_time_of_one_build_on_a_closed_case")
CELL_COUNT_RTOL = tol(
    "mesh_engine_conformance__cell_count_at_a_uniform_cell_size_against_the_area_over_the_"
    "size_squared_relative"
)

GMSH_ENGINE_IDS = ("triangle",)
"""The built-in engines that need the optional ``mesh`` extra (gmsh)."""

SIDES = ("west", "east", "south", "north")

pytestmark = pytest.mark.xdist_group("mesh_engine_contract")
"""One worker runs the file, so each mesh is built once per engine and per case."""


# --------------------------------------------------------------------------- #
# Engines under test
# --------------------------------------------------------------------------- #


def _cannot_run(reason: str) -> None:
    """Skip, or fail when the environment promised the extra."""
    if os.environ.get("HMP_REQUIRE_GMSH"):
        pytest.fail(f"HMP_REQUIRE_GMSH is set and {reason}")
    pytest.skip(reason)


def _engine(engine_id: str) -> MeshEngine:
    """Build what the registry serves under *engine_id*, or skip it if it cannot run here.

    A built-in this environment cannot load or run is a skip. A plugin that fails
    to build is not: ``mesh_engines.load_plugins``
    already dropped the ones that cannot load, so an id that survived to here and
    then fails is a defect of the engine.
    """
    if engine_id in GMSH_ENGINE_IDS and find_spec("gmsh") is None:
        _cannot_run(f"{engine_id!r} needs gmsh, which is not installed here")
    try:
        return registry.mesh_engines.create(engine_id)
    except MeshRequestError:
        if engine_id in registry.mesh_engines.names(shipped_only=True):
            _cannot_run(f"{engine_id!r} is declared by this build and cannot be loaded here")
        raise


@pytest.fixture(params=registry.mesh_engines.names())
def engine_id(request) -> str:
    """The id of one mesh engine, once per implementation this installation serves."""
    return request.param


@pytest.fixture
def engine(engine_id: str) -> MeshEngine:
    """The engine served under ``engine_id``, skipped when it cannot run here."""
    return _engine(engine_id)


# --------------------------------------------------------------------------- #
# Field situations
# --------------------------------------------------------------------------- #

RIVER = LineString([(100.0, 150.0), (450.0, 420.0), (700.0, 520.0), (900.0, 880.0)])
CONTACT = LineString([(400.0, 0.0), (600.0, 1000.0)])
"""A straight contact: the side of a point is the sign of its cross product with the chord."""
WEST_UNIT, EAST_UNIT = "west_unit", "east_unit"
HOLE = box(300.0, 300.0, 500.0, 500.0)
SQUARE_SIDE_M = 1000.0


def _square(river: LineString, contact: LineString, west_on_left: bool) -> MeshRequest:
    """The 1 km square catchment at 50 m with a river (``cell``) and a contact (``face``)."""
    left, right = (WEST_UNIT, EAST_UNIT) if west_on_left else (EAST_UNIT, WEST_UNIT)
    return mesh_request(
        grid_over(square_domain(SQUARE_SIDE_M), 25.0, crs_wkt=LAMBERT93_WKT),
        nominal_size_m=50.0,
        lines=(
            LineFamilySpec("rivers", "cell", (shapely.segmentize(river, 50.0),)),
            LineFamilySpec(
                "geology",
                "face",
                (shapely.segmentize(contact, 50.0),),
                zone_left=(left,),
                zone_right=(right,),
            ),
        ),
    )


def square_case() -> MeshRequest:
    """A 1 km square whose river runs north-east across a contact drawn northward."""
    return _square(RIVER, CONTACT, west_on_left=True)


def lines_drawn_the_other_way_case() -> MeshRequest:
    """The same square with the river and the contact drawn from their other end."""
    return _square(RIVER.reverse(), CONTACT.reverse(), west_on_left=False)


def square_with_a_hole_case() -> MeshRequest:
    """A 1 km square with a 200 m hole, and a river that passes beside the hole."""
    river = LineString([(700.0, 0.0), (700.0, SQUARE_SIDE_M)])
    return mesh_request(
        grid_over(square_domain(SQUARE_SIDE_M), 25.0, crs_wkt=LAMBERT93_WKT),
        domain=square_domain(SQUARE_SIDE_M).difference(HOLE),
        nominal_size_m=50.0,
        lines=(LineFamilySpec("rivers", "cell", (shapely.segmentize(river, 50.0),)),),
    )


def island_case() -> MeshRequest:
    """A circular island of 200 m radius, no line."""
    return mesh_request(
        grid_over((-200.0, -200.0, 200.0, 200.0), 10.0, crs_wkt=LAMBERT93_WKT),
        domain=Point(0.0, 0.0).buffer(200.0, quad_segs=16),
        nominal_size_m=20.0,
    )


def ramp_case() -> MeshRequest:
    """A 500 m by 200 m rectangle whose size field grows from 10 m (west) to 50 m (east)."""
    grid = grid_over((0.0, 0.0, 500.0, 200.0), 10.0, crs_wkt=LAMBERT93_WKT)
    x = grid.xmin + (np.arange(grid.ncol) + 0.5) * grid.dx
    size = np.tile(10.0 + 40.0 * x / 500.0, (grid.nrow, 1))
    return mesh_request(grid, nominal_size_m=50.0, size_field=SizeField(size, grid))


def _uniform(*, sized: bool) -> MeshRequest:
    """A 4 km square at 100 m, given as a uniform size field or as the nominal size alone."""
    grid = grid_over(square_domain(4000.0), 25.0, crs_wkt=LAMBERT93_WKT)
    field = uniform_size_field(grid, 100.0) if sized else None
    return mesh_request(grid, nominal_size_m=100.0, size_field=field)


def uniform_size_field_case() -> MeshRequest:
    """A 4 km square at a uniform 100 m size field."""
    return _uniform(sized=True)


def nominal_size_only_case() -> MeshRequest:
    """A 4 km square at a nominal size of 100 m and no size field."""
    return _uniform(sized=False)


def given_triangulation_case() -> MeshRequest:
    """A 1 km square already triangulated on a 6 x 6 vertex lattice."""
    axis = np.linspace(0.0, SQUARE_SIDE_M, 6)
    vertices = np.array([(x, y) for y in axis for x in axis])
    triangles = []
    for j in range(5):
        for i in range(5):
            n00, n10 = j * 6 + i, j * 6 + i + 1
            n01, n11 = (j + 1) * 6 + i, (j + 1) * 6 + i + 1
            triangles += [(n00, n10, n11), (n00, n11, n01)]
    return mesh_request(
        grid_over(square_domain(SQUARE_SIDE_M), 25.0, crs_wkt=LAMBERT93_WKT),
        nominal_size_m=200.0,
        input_triangulation=InputTriangulation(vertices, np.array(triangles), {}),
    )


CASES: dict[str, Callable[[], MeshRequest]] = {
    "square": square_case,
    "lines_drawn_the_other_way": lines_drawn_the_other_way_case,
    "square_with_a_hole": square_with_a_hole_case,
    "island": island_case,
    "ramp": ramp_case,
    "uniform_size_field": uniform_size_field_case,
    "nominal_size_only": nominal_size_only_case,
    "given_triangulation": given_triangulation_case,
}
"""Every field situation, by name. An engine may refuse only the given triangulation."""

EVERY_CASE = tuple(CASES)
MESHED_BY_THE_ENGINE = tuple(case for case in CASES if case != "given_triangulation")
"""The cases whose cells the engine draws itself; a given triangulation keeps its own edges."""
WITH_A_RIVER = ("square", "lines_drawn_the_other_way", "square_with_a_hole")
WITH_A_CONTACT = ("square", "lines_drawn_the_other_way")
ON_THE_1_KM_SQUARE = ("square", "lines_drawn_the_other_way", "square_with_a_hole")
WITH_A_CURVED_OR_HOLED_OUTLINE = ("island", "square_with_a_hole")
AT_A_UNIFORM_SIZE = ("uniform_size_field", "nominal_size_only")


def _built(engine: MeshEngine, request: MeshRequest) -> PlanarCellMesh:
    """Build, within the time budget."""
    start = time.perf_counter()
    cell_mesh = engine.build(request)
    elapsed = time.perf_counter() - start
    assert elapsed < BUDGET_S, f"{type(engine).engine_id!r} took {elapsed:.1f} s on a closed case"
    return cell_mesh


@functools.cache
def _mesh(engine_id: str, case: str) -> PlanarCellMesh | None:
    """The mesh of *case* by *engine_id*, built once; ``None`` when it refuses a given triangulation."""
    request = CASES[case]()
    engine = registry.mesh_engines.create(engine_id)
    if request.input_triangulation is None:
        return _built(engine, request)
    try:
        return _built(engine, request)
    except MeshRequestError:
        return None


def _mesh_or_skip(engine_id: str, case: str) -> PlanarCellMesh:
    cell_mesh = _mesh(engine_id, case)
    if cell_mesh is None:
        pytest.skip("this engine refuses a given triangulation by MeshRequestError")
    return cell_mesh


def _area_to_cover(request: MeshRequest, structured: bool) -> float:
    grid = request.grid
    if structured:
        return (grid.xmax - grid.xmin) * (grid.ymax - grid.ymin)
    return request.domain.area


def _left_of(line: LineString, points: np.ndarray) -> np.ndarray:
    """Cross product of each point with the chord of a straight *line*: positive on its left."""
    start, end = np.asarray(line.coords[0]), np.asarray(line.coords[-1])
    chord, offset = end - start, np.asarray(points) - start
    return chord[0] * offset[:, 1] - chord[1] * offset[:, 0]


# --------------------------------------------------------------------------- #
# Invariants
# --------------------------------------------------------------------------- #


def assert_the_mesh_names_its_engine_and_its_request(
    cell_mesh: PlanarCellMesh, engine_cls: type, request: MeshRequest
) -> None:
    assert cell_mesh.identity.engine_id == engine_cls.engine_id
    assert cell_mesh.identity.engine_version == engine_cls.engine_version
    assert cell_mesh.identity.request_hash == request.canonical_hash()
    assert cell_mesh.crs_wkt == request.crs_wkt
    if engine_cls.capabilities.deterministic:
        assert cell_mesh.identity.seed in (None, request.seed)


def assert_the_quality_report_is_whole(
    cell_mesh: PlanarCellMesh, capabilities: MeshEngineCapabilities
) -> None:
    qa = cell_mesh.qa.as_dict()
    for field in (
        "n_cells",
        "area_sum_m2",
        "area_quantiles_m2",
        "size_quantiles_m",
        "neighbour_ratio",
        "center_offset",
        "nonorthogonality_deg",
        "bisection_offset",
        "min_angle_deg",
        "max_angle_deg",
        "n_concave_cells",
        "min_face_length_m",
        "n_degenerate_faces",
        "n_duplicate_vertices_in_cells",
        "size_fidelity",
        "families",
        "declarations",
        "notes",
        "extras",
    ):
        assert field in qa, f"MeshQA lacks {field}"
    assert qa["n_cells"] == cell_mesh.n_cells
    assert set(qa["declarations"]) == DECLARATION_KEYS
    assert qa["declarations"] == capabilities.declarations()


def assert_the_area_is_the_area_to_cover(
    cell_mesh: PlanarCellMesh, request: MeshRequest, structured: bool
) -> None:
    wanted = _area_to_cover(request, structured)
    assert abs(cell_mesh.qa.area_sum_m2 - wanted) <= AREA_RTOL * wanted
    assert abs(float(cell_mesh.geometry.areas.sum()) - wanted) <= AREA_RTOL * wanted


def assert_no_cell_repeats_a_vertex_and_no_face_is_null(cell_mesh: PlanarCellMesh) -> None:
    assert cell_mesh.qa.n_duplicate_vertices_in_cells == 0
    assert cell_mesh.qa.n_degenerate_faces == 0
    assert np.all(cell_mesh.geometry.areas > 0.0)


def assert_each_centre_lies_in_its_cell(cell_mesh: PlanarCellMesh) -> None:
    polygons = cell_polygons(cell_mesh.mesh.vertices, cell_mesh.connectivity_rows)
    assert all(polygon is not None for polygon in polygons)
    covered = shapely.covers(polygons, shapely.points(cell_mesh.centers))
    assert covered.all(), (
        f"{int((~covered).sum())} of {covered.size} centres are outside their cell"
    )


def assert_a_boundary_face_has_no_second_cell(cell_mesh: PlanarCellMesh) -> None:
    table = cell_mesh.face_families
    for index, family in enumerate(table.names):
        if family.startswith("boundary:"):
            assert np.all(table.cell_b[table.family == index] == -1), family


def assert_each_side_is_a_boundary_family_of_its_length(
    cell_mesh: PlanarCellMesh, side_m: float
) -> None:
    for side in SIDES:
        assert cell_mesh.face_rows(f"boundary:{side}").any(), f"no face on the {side} side"
        assert cell_mesh.qa.families[f"boundary:{side}"]["length_m"] == pytest.approx(side_m)


def assert_each_row_runs_with_its_first_cell_on_the_left(cell_mesh: PlanarCellMesh) -> None:
    """``node_a -> node_b`` keeps ``cell_a`` on its left and ``cell_b`` on its right."""
    table = cell_mesh.face_families
    vertices = cell_mesh.mesh.vertices
    start = vertices[table.node_a]
    face = vertices[table.node_b] - start
    centroids = cell_mesh.geometry.area_centroids

    def side(cells: np.ndarray) -> np.ndarray:
        offset = centroids[np.maximum(cells, 0)] - start
        return face[:, 0] * offset[:, 1] - face[:, 1] * offset[:, 0]

    inside = table.cell_b >= 0
    assert np.all(side(table.cell_a) > 0.0)
    assert np.all(side(table.cell_b)[inside] < 0.0)


def assert_each_river_is_one_continuous_chain(cell_mesh: PlanarCellMesh, structured: bool) -> None:
    """Two neighbors of a chain share a face, or a corner on a structured grid."""
    padded = cell_mesh.geometry.padded_connectivity
    chains = cell_mesh.chains("rivers")
    assert chains, "the river produced no chain"
    for chain in chains:
        assert chain.cell_ids.size >= 2
        for first, second in zip(chain.cell_ids[:-1], chain.cell_ids[1:], strict=True):
            if first == second:
                continue
            joined = int(second) in cell_mesh.geometry.neighbours(int(first))
            corner = set(padded[first][padded[first] >= 0]) & set(
                padded[second][padded[second] >= 0]
            )
            assert joined or (structured and bool(corner))


def assert_a_river_chain_runs_the_way_its_river_is_drawn(
    cell_mesh: PlanarCellMesh, river: LineString
) -> None:
    (chain,) = cell_mesh.chains("rivers")
    along = shapely.line_locate_point(river, shapely.points(cell_mesh.centers[chain.cell_ids]))
    assert np.all(np.diff(along) >= 0.0)
    assert along[-1] > along[0]


def assert_the_cells_of_a_river_stay_near_it(cell_mesh: PlanarCellMesh) -> None:
    quality = cell_mesh.qa.families["rivers"]
    largest_cell_m = float(np.sqrt(cell_mesh.qa.area_quantiles_m2["max"]))
    assert quality["breaks"] == 0.0
    assert quality["max_line_offset_m"] <= 2.0 * largest_cell_m


def assert_the_first_cell_of_a_river_row_is_in_the_chain(cell_mesh: PlanarCellMesh) -> None:
    rows = cell_mesh.face_rows("rivers")
    in_chains = {int(cell) for chain in cell_mesh.chains("rivers") for cell in chain.cell_ids}
    assert set(cell_mesh.face_families.cell_a[rows].tolist()) <= in_chains


def assert_a_face_family_is_published_with_its_distance_to_the_line(
    cell_mesh: PlanarCellMesh, extent_m: float, exact_faces: bool
) -> None:
    quality = cell_mesh.qa.families["geology"]
    assert cell_mesh.face_rows("geology").any()
    assert "hausdorff_m" in quality
    assert quality["covered_length_rel"] >= 0.0
    if exact_faces:
        assert quality["hausdorff_m"] <= HAUSDORFF_RTOL * extent_m
        assert quality["covered_length_rel"] == pytest.approx(1.0, abs=HAUSDORFF_RTOL)


def assert_the_cell_on_the_left_of_a_contact_comes_first(
    cell_mesh: PlanarCellMesh, contact: LineString
) -> None:
    """A staircase cell may sit on the line; the first cell is never right of the second."""
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology") & (table.cell_b >= 0)
    centroids = cell_mesh.geometry.area_centroids
    left = _left_of(contact, centroids[table.cell_a[rows]])
    right = _left_of(contact, centroids[table.cell_b[rows]])
    assert rows.any()
    assert np.all(left >= 0.0)
    assert np.all(right <= 0.0)
    assert np.all(left > right)


def assert_a_face_family_names_the_zones_of_its_sides(
    cell_mesh: PlanarCellMesh, spec: LineFamilySpec
) -> None:
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(spec.name)
    left = {cell_mesh.zone_names[z] for z in table.zone_left[rows] if z >= 0}
    right = {cell_mesh.zone_names[z] for z in table.zone_right[rows] if z >= 0}
    assert {*spec.zone_left, *spec.zone_right} <= set(cell_mesh.zone_names)
    assert left == set(spec.zone_left)
    assert right == set(spec.zone_right)


def assert_the_cells_stay_inside_the_domain(cell_mesh: PlanarCellMesh, domain: Polygon) -> None:
    xmin, ymin, xmax, ymax = domain.bounds
    margin_m = 1.0e-6 * max(xmax - xmin, ymax - ymin)
    union = shapely.union_all(cell_polygons(cell_mesh.mesh.vertices, cell_mesh.connectivity_rows))
    outside = union.difference(domain.buffer(margin_m))
    assert outside.area <= AREA_RTOL * domain.area


def assert_no_centre_lies_in_a_hole(cell_mesh: PlanarCellMesh, domain: Polygon) -> None:
    for ring in domain.interiors:
        assert not shapely.contains_xy(Polygon(ring), *cell_mesh.centers.T).any()


# --------------------------------------------------------------------------- #
# The port
# --------------------------------------------------------------------------- #


def test_the_builtin_engines_are_all_declared() -> None:
    """The floor: dropping a built-in from the registry cannot pass silently."""
    assert {"regular", "triangle", "voronoi"} <= set(registry.mesh_engines.names())


def test_an_engine_satisfies_the_port(engine_id: str, engine: MeshEngine) -> None:
    cls = type(engine)

    assert isinstance(engine, MeshEngine)
    assert missing_engine_members(cls) == ()
    assert cls.engine_id == engine_id
    assert registry.mesh_engines.get(engine_id) is cls
    assert cls.engine_version.strip()
    assert cls.capabilities.cell_types


# --------------------------------------------------------------------------- #
# Invariants on every field situation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", EVERY_CASE)
def test_a_mesh_states_who_built_it_and_from_which_request(engine_id, engine, case) -> None:
    cell_mesh = _mesh_or_skip(engine_id, case)

    assert_the_mesh_names_its_engine_and_its_request(cell_mesh, type(engine), CASES[case]())


@pytest.mark.parametrize("case", EVERY_CASE)
def test_a_mesh_carries_the_whole_quality_report(engine_id, engine, case) -> None:
    cell_mesh = _mesh_or_skip(engine_id, case)

    assert_the_quality_report_is_whole(cell_mesh, type(engine).capabilities)


@pytest.mark.parametrize("case", EVERY_CASE)
def test_a_mesh_follows_the_capabilities_the_engine_declares(engine_id, engine, case) -> None:
    cell_mesh = _mesh_or_skip(engine_id, case)
    capabilities = type(engine).capabilities

    assert cell_mesh.mesh.cell_types[0] in capabilities.cell_types
    assert (cell_mesh.structured_shape is not None) == capabilities.structured


@pytest.mark.parametrize("case", EVERY_CASE)
def test_the_cell_areas_add_up_to_the_area_to_cover(engine_id, engine, case) -> None:
    cell_mesh = _mesh_or_skip(engine_id, case)

    assert_the_area_is_the_area_to_cover(
        cell_mesh, CASES[case](), type(engine).capabilities.structured
    )


@pytest.mark.parametrize("case", EVERY_CASE)
def test_no_cell_repeats_a_vertex_and_no_face_is_null(engine_id, engine, case) -> None:
    assert_no_cell_repeats_a_vertex_and_no_face_is_null(_mesh_or_skip(engine_id, case))


@pytest.mark.parametrize("case", EVERY_CASE)
def test_the_center_of_a_cell_lies_in_the_cell(engine_id, engine, case) -> None:
    assert_each_centre_lies_in_its_cell(_mesh_or_skip(engine_id, case))


@pytest.mark.parametrize("case", EVERY_CASE)
def test_a_boundary_face_has_no_second_cell(engine_id, engine, case) -> None:
    cell_mesh = _mesh_or_skip(engine_id, case)
    if cell_mesh.face_families is None:
        pytest.skip(f"{case}: no face family on this case, nothing to check")

    assert_a_boundary_face_has_no_second_cell(cell_mesh)


@pytest.mark.parametrize("case", MESHED_BY_THE_ENGINE)
def test_an_engine_with_exact_faces_runs_each_row_with_its_first_cell_on_the_left(
    engine_id, engine, case
) -> None:
    if not type(engine).capabilities.exact_faces:
        pytest.skip("a staircase face is not oriented along its line")
    cell_mesh = _mesh_or_skip(engine_id, case)
    if cell_mesh.face_families is None:
        pytest.skip(f"{case}: no face family on this case, nothing to check")

    assert_each_row_runs_with_its_first_cell_on_the_left(cell_mesh)


@pytest.mark.parametrize("case", ON_THE_1_KM_SQUARE)
def test_the_four_sides_of_a_square_are_boundary_families_of_its_side(
    engine_id, engine, case
) -> None:
    assert_each_side_is_a_boundary_family_of_its_length(
        _mesh_or_skip(engine_id, case), SQUARE_SIDE_M
    )


@pytest.mark.parametrize("case", WITH_A_CURVED_OR_HOLED_OUTLINE)
def test_the_cells_of_an_unstructured_engine_stay_inside_the_domain(
    engine_id, engine, case
) -> None:
    """A structured engine covers the DEM rectangle; any other tiles the domain and its holes."""
    if type(engine).capabilities.structured:
        pytest.skip("a structured engine covers the DEM rectangle, not the domain")
    cell_mesh = _mesh_or_skip(engine_id, case)
    domain = CASES[case]().domain

    assert_the_cells_stay_inside_the_domain(cell_mesh, domain)
    assert_no_centre_lies_in_a_hole(cell_mesh, domain)


# --------------------------------------------------------------------------- #
# Rivers and contacts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", WITH_A_RIVER)
def test_a_river_is_a_continuous_chain_of_cells(engine_id, engine, case) -> None:
    assert_each_river_is_one_continuous_chain(
        _mesh_or_skip(engine_id, case), type(engine).capabilities.structured
    )


@pytest.mark.parametrize("case", WITH_A_RIVER)
def test_a_river_chain_runs_the_way_its_river_is_drawn(engine_id, engine, case) -> None:
    river = CASES[case]().family("rivers").lines[0]

    assert_a_river_chain_runs_the_way_its_river_is_drawn(_mesh_or_skip(engine_id, case), river)


@pytest.mark.parametrize("case", WITH_A_RIVER)
def test_the_cells_of_a_river_stay_near_the_river(engine_id, engine, case) -> None:
    assert_the_cells_of_a_river_stay_near_it(_mesh_or_skip(engine_id, case))


@pytest.mark.parametrize("case", WITH_A_RIVER)
def test_the_first_cell_of_a_river_face_is_in_the_river_chain(engine_id, engine, case) -> None:
    assert_the_first_cell_of_a_river_row_is_in_the_chain(_mesh_or_skip(engine_id, case))


@pytest.mark.parametrize("case", WITH_A_CONTACT)
def test_a_face_family_is_published_with_its_distance_to_the_line(engine_id, engine, case) -> None:
    assert_a_face_family_is_published_with_its_distance_to_the_line(
        _mesh_or_skip(engine_id, case), SQUARE_SIDE_M, type(engine).capabilities.exact_faces
    )


@pytest.mark.parametrize("case", WITH_A_CONTACT)
def test_the_cell_on_the_left_of_a_contact_is_the_first_cell_of_its_face(
    engine_id, engine, case
) -> None:
    contact = CASES[case]().family("geology").lines[0]

    assert_the_cell_on_the_left_of_a_contact_comes_first(_mesh_or_skip(engine_id, case), contact)


@pytest.mark.parametrize("case", WITH_A_CONTACT)
def test_a_face_family_names_the_zones_on_each_side(engine_id, engine, case) -> None:
    spec = CASES[case]().family("geology")

    assert_a_face_family_names_the_zones_of_its_sides(_mesh_or_skip(engine_id, case), spec)


# --------------------------------------------------------------------------- #
# Declarations
# --------------------------------------------------------------------------- #


def test_a_graded_engine_follows_the_size_ramp(engine_id, engine) -> None:
    if not type(engine).capabilities.graded:
        pytest.skip("this engine does not grade its cells")
    cell_mesh = _mesh_or_skip(engine_id, "ramp")
    x = cell_mesh.centers[:, 0]
    areas = cell_mesh.geometry.areas

    assert areas[x > 400.0].mean() > 2.0 * areas[x < 100.0].mean()


@pytest.mark.parametrize("case", AT_A_UNIFORM_SIZE)
def test_a_uniform_cell_size_gives_the_area_over_its_square_in_cells(
    engine_id, engine, case
) -> None:
    """A cell size is the side of the square of the same mean area, whatever the engine."""
    request = CASES[case]()
    cell_mesh = _mesh_or_skip(engine_id, case)
    area = _area_to_cover(request, type(engine).capabilities.structured)

    expected = area / request.nominal_size_m**2
    assert cell_mesh.n_cells == pytest.approx(expected, rel=CELL_COUNT_RTOL)


def test_a_deterministic_engine_builds_the_same_mesh_twice(engine_id, engine) -> None:
    if not type(engine).capabilities.deterministic:
        pytest.skip("this engine does not declare itself deterministic")
    first = _mesh_or_skip(engine_id, "square")
    np.random.seed(12345)
    random.seed(12345)
    second = _built(engine, square_case())

    np.testing.assert_array_equal(first.mesh.vertices, second.mesh.vertices)
    np.testing.assert_array_equal(first.connectivity_rows, second.connectivity_rows)
    np.testing.assert_array_equal(first.centers, second.centers)
    assert [chain.cell_ids.tolist() for chain in first.cell_chains] == [
        chain.cell_ids.tolist() for chain in second.cell_chains
    ]
    assert first.qa.as_dict() == second.qa.as_dict()


def test_an_engine_that_uses_a_given_triangulation_keeps_its_cells(engine_id, engine) -> None:
    request = given_triangulation_case()
    cell_mesh = _mesh_or_skip(engine_id, "given_triangulation")
    triangulation = request.input_triangulation

    if type(engine).capabilities.cell_types == (CellType.TRIANGLE,):
        assert cell_mesh.n_cells == len(triangulation.triangles)
    assert abs(cell_mesh.qa.area_sum_m2 - request.domain.area) <= AREA_RTOL * request.domain.area


def test_an_engine_refuses_a_request_it_cannot_honour_by_a_typed_error(engine) -> None:
    """A size finer than a structured engine can give is refused, never silently coarsened."""
    if not type(engine).capabilities.structured:
        pytest.skip("only a structured engine is bound to the DEM pitch")
    request = square_case()
    finer = mesh_request(request.grid, nominal_size_m=request.grid.dx / 2.0)

    with pytest.raises(MeshRequestError):
        engine.build(finer)


def test_the_module_exposes_its_registry_and_none_of_the_retired_functions() -> None:
    """The registry is one object of the shared engine, read through ``mesh_engines``."""
    held = registry.mesh_engines

    assert isinstance(held, PluginRegistry)
    assert held.id_attributes == ("engine_id",)
    assert held.group == registry.ENTRY_POINT_GROUP
    assert held.default_id == registry.DEFAULT_ENGINE_ID
    assert held.names(shipped_only=True) == tuple(sorted(registry._BUILTIN_PATHS))
    retired = (
        "get",
        "create",
        "register",
        "unregister",
        "load_plugins",
        "is_registered",
        "resolve_id",
        "list_engine_ids",
        "builtin_engine_ids",
    )
    assert [name for name in retired if hasattr(registry, name)] == []
