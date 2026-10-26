"""Conformance suite for the mesh port, run against every engine.

Almost every assertion takes the ``engine`` fixture, and that fixture is
parametrized over what :mod:`hydromodpy.spatial.mesh.registry` resolves, not over
a list this file keeps. An engine installed beside this build is therefore run
by this suite without a line of ``tests/`` naming it. ``register()`` certifies a
class on the members it declares; the invariants a solver relies on (cells cover
their centres, the areas add up, a chain is continuous) are only visible on a
mesh, and this file is where they are checked.

The cases are closed: on a 1 km square, a circular island and a rectangle the
answer is known (the area, the line a face family must follow, the direction of
a size ramp), so the assertions are exact rather than banded. Invariants are
conditioned on what the engine declares in its capabilities: a structured engine
covers the DEM rectangle, a graded engine follows a size ramp, an engine with
exact faces follows its face lines to ``HAUSDORFF_RTOL`` of the extent, a
deterministic engine builds the same mesh twice.

A built-in engine this environment cannot run is skipped, unless
``HMP_REQUIRE_GMSH`` is set (CI with the ``mesh`` extra, a developer machine):
a green run that skipped two of the three engines proves nothing there.
"""

from __future__ import annotations

import os
import random
import time
from importlib.util import find_spec

import numpy as np
import pytest
import shapely
from pyproj import CRS
from shapely.geometry import LineString, Point, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh import MeshEngine, PlanarCellMesh, registry
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.mesh_qa import DECLARATION_KEYS
from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons
from hydromodpy.spatial.mesh.port import missing_engine_members
from hydromodpy.spatial.mesh.request import (
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
    SizeField,
)
from tests._helpers.tolerances import tol

CRS_WKT = CRS.from_epsg(2154).to_wkt()

AREA_RTOL = tol("mesh_engine_conformance__sum_of_the_cell_areas_against_the_area_to_cover_relative")
HAUSDORFF_RTOL = tol(
    "mesh_engine_conformance__exact_faces_to_their_source_lines_"
    "hausdorff_distance_as_a_share_of_the_extent"
)
BUDGET_S = tol("mesh_engine_conformance__wall_clock_time_of_one_build_on_a_closed_case")

GMSH_ENGINE_IDS = ("triangle",)
"""The built-in engines that need the optional ``mesh`` extra (gmsh)."""

SIDES = ("west", "east", "south", "north")


# --------------------------------------------------------------------------- #
# Engines under test
# --------------------------------------------------------------------------- #


def _cannot_run(reason: str) -> None:
    """Skip, or fail when the environment promised the extra."""
    if os.environ.get("HMP_REQUIRE_GMSH"):
        pytest.fail(f"HMP_REQUIRE_GMSH is set and {reason}")
    pytest.skip(reason)


def _engine(engine_id: str):
    """Build what the registry serves under *engine_id*, or skip it if it cannot run here.

    A built-in this environment cannot load or run is a skip. A plugin that fails
    to build is not: :func:`~hydromodpy.spatial.mesh.registry.load_plugins`
    already dropped the ones that cannot load, so an id that survived to here and
    then fails is a defect of the engine.
    """
    if engine_id in GMSH_ENGINE_IDS and find_spec("gmsh") is None:
        _cannot_run(f"{engine_id!r} needs gmsh, which is not installed here")
    try:
        return registry.create(engine_id)
    except MeshRequestError:
        if engine_id in registry.builtin_engine_ids():
            _cannot_run(f"{engine_id!r} is declared by this build and cannot be loaded here")
        raise


@pytest.fixture(params=registry.list_engine_ids())
def engine(request) -> MeshEngine:
    """One mesh engine, once per implementation this installation serves."""
    return _engine(request.param)


# --------------------------------------------------------------------------- #
# Closed cases
# --------------------------------------------------------------------------- #


def _grid(xmin: float, xmax: float, ymin: float, ymax: float, pitch: float) -> RasterGridSpec:
    return RasterGridSpec(
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        dx=pitch,
        dy=pitch,
        nrow=round((ymax - ymin) / pitch),
        ncol=round((xmax - xmin) / pitch),
        crs_wkt=CRS_WKT,
    )


RIVER = LineString([(100.0, 150.0), (450.0, 420.0), (700.0, 520.0), (900.0, 880.0)])
CONTACT = LineString([(400.0, 0.0), (600.0, 1000.0)])
WEST_UNIT, EAST_UNIT = "west_unit", "east_unit"


def square_case() -> MeshRequest:
    """A 1 km square with a river (``cell``) that crosses a geological contact (``face``)."""
    return MeshRequest(
        domain=box(0.0, 0.0, 1000.0, 1000.0),
        crs_wkt=CRS_WKT,
        grid=_grid(0.0, 1000.0, 0.0, 1000.0, 25.0),
        nominal_size_m=50.0,
        lines=(
            LineFamilySpec("rivers", "cell", (shapely.segmentize(RIVER, 50.0),)),
            LineFamilySpec(
                "geology",
                "face",
                (shapely.segmentize(CONTACT, 50.0),),
                zone_left=(WEST_UNIT,),
                zone_right=(EAST_UNIT,),
            ),
        ),
    )


def island_case() -> MeshRequest:
    """A circular island of 200 m radius, no line."""
    return MeshRequest(
        domain=Point(0.0, 0.0).buffer(200.0, quad_segs=16),
        crs_wkt=CRS_WKT,
        grid=_grid(-200.0, 200.0, -200.0, 200.0, 10.0),
        nominal_size_m=20.0,
    )


def ramp_case() -> MeshRequest:
    """A 500 m by 200 m rectangle whose size field grows from 10 m (west) to 50 m (east)."""
    grid = _grid(0.0, 500.0, 0.0, 200.0, 10.0)
    x = grid.xmin + (np.arange(grid.ncol) + 0.5) * grid.dx
    size = np.tile(10.0 + 40.0 * x / 500.0, (grid.nrow, 1))
    return MeshRequest(
        domain=box(0.0, 0.0, 500.0, 200.0),
        crs_wkt=CRS_WKT,
        grid=grid,
        nominal_size_m=50.0,
        size_field=SizeField(size, grid),
    )


def given_triangulation_case() -> MeshRequest:
    """A 1 km square already triangulated on a 6 x 6 vertex lattice."""
    axis = np.linspace(0.0, 1000.0, 6)
    vertices = np.array([(x, y) for y in axis for x in axis])
    triangles = []
    for j in range(5):
        for i in range(5):
            n00, n10 = j * 6 + i, j * 6 + i + 1
            n01, n11 = (j + 1) * 6 + i, (j + 1) * 6 + i + 1
            triangles += [(n00, n10, n11), (n00, n11, n01)]
    return MeshRequest(
        domain=box(0.0, 0.0, 1000.0, 1000.0),
        crs_wkt=CRS_WKT,
        grid=_grid(0.0, 1000.0, 0.0, 1000.0, 25.0),
        nominal_size_m=200.0,
        input_triangulation=InputTriangulation(vertices, np.array(triangles), {}),
    )


CASES = {
    "square": square_case,
    "island": island_case,
    "ramp": ramp_case,
    "given_triangulation": given_triangulation_case,
}


@pytest.fixture(params=sorted(CASES))
def case(request) -> tuple[str, MeshRequest]:
    return request.param, CASES[request.param]()


def _built(engine, request: MeshRequest) -> PlanarCellMesh:
    """Build, within the time budget."""
    start = time.perf_counter()
    cell_mesh = engine.build(request)
    elapsed = time.perf_counter() - start
    assert elapsed < BUDGET_S, f"{type(engine).engine_id!r} took {elapsed:.1f} s on a closed case"
    return cell_mesh


def _built_or_refused(engine, name: str, request: MeshRequest) -> PlanarCellMesh | None:
    """Build, or ``None`` when the engine refuses a given triangulation by ``MeshRequestError``."""
    if name != "given_triangulation":
        return _built(engine, request)
    try:
        return _built(engine, request)
    except MeshRequestError:
        return None


def _area_to_cover(request: MeshRequest, structured: bool) -> float:
    grid = request.grid
    if structured:
        return (grid.xmax - grid.xmin) * (grid.ymax - grid.ymin)
    return request.domain.area


# --------------------------------------------------------------------------- #
# The port
# --------------------------------------------------------------------------- #


def test_the_builtin_engines_are_all_declared() -> None:
    """The floor: dropping a built-in from the registry cannot pass silently."""
    assert {"regular", "triangle", "voronoi"} <= set(registry.list_engine_ids())


def test_an_engine_satisfies_the_port(engine) -> None:
    cls = type(engine)

    assert isinstance(engine, MeshEngine)
    assert missing_engine_members(cls) == ()
    assert registry.get(cls.engine_id) is cls
    assert cls.engine_version.strip()
    assert cls.capabilities.cell_types


# --------------------------------------------------------------------------- #
# Invariants on every closed case
# --------------------------------------------------------------------------- #


def test_a_mesh_states_who_built_it_and_from_which_request(engine, case) -> None:
    name, request = case
    cell_mesh = _built_or_refused(engine, name, request)
    if cell_mesh is None:
        return
    cls = type(engine)

    assert cell_mesh.identity.engine_id == cls.engine_id
    assert cell_mesh.identity.engine_version == cls.engine_version
    assert cell_mesh.identity.request_hash == request.canonical_hash()
    assert cell_mesh.crs_wkt == request.crs_wkt
    if cls.capabilities.deterministic:
        assert cell_mesh.identity.seed in (None, request.seed)


def test_a_mesh_carries_the_whole_quality_report(engine, case) -> None:
    name, request = case
    cell_mesh = _built_or_refused(engine, name, request)
    if cell_mesh is None:
        return
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
    assert qa["declarations"] == type(engine).capabilities.declarations()


def test_a_mesh_follows_the_capabilities_the_engine_declares(engine, case) -> None:
    name, request = case
    cell_mesh = _built_or_refused(engine, name, request)
    if cell_mesh is None:
        return
    capabilities = type(engine).capabilities

    assert cell_mesh.mesh.cell_types[0] in capabilities.cell_types
    assert (cell_mesh.structured_shape is not None) == capabilities.structured


def test_the_cell_areas_add_up_to_the_area_to_cover(engine, case) -> None:
    name, request = case
    cell_mesh = _built_or_refused(engine, name, request)
    if cell_mesh is None:
        return
    wanted = _area_to_cover(request, type(engine).capabilities.structured)

    assert abs(cell_mesh.qa.area_sum_m2 - wanted) <= AREA_RTOL * wanted
    assert abs(float(cell_mesh.geometry.areas.sum()) - wanted) <= AREA_RTOL * wanted


def test_no_cell_repeats_a_vertex_and_no_face_is_null(engine, case) -> None:
    name, request = case
    cell_mesh = _built_or_refused(engine, name, request)
    if cell_mesh is None:
        return

    assert cell_mesh.qa.n_duplicate_vertices_in_cells == 0
    assert cell_mesh.qa.n_degenerate_faces == 0
    assert np.all(cell_mesh.geometry.areas > 0.0)


def test_the_center_of_a_cell_lies_in_the_cell(engine, case) -> None:
    name, request = case
    cell_mesh = _built_or_refused(engine, name, request)
    if cell_mesh is None:
        return
    polygons = cell_polygons(cell_mesh.mesh.vertices, cell_mesh.connectivity_rows)

    assert all(polygon is not None for polygon in polygons)
    covered = shapely.covers(polygons, shapely.points(cell_mesh.centers))
    assert covered.all(), (
        f"{int((~covered).sum())} of {covered.size} centres are outside their cell"
    )


def test_a_boundary_face_has_no_second_cell(engine, case) -> None:
    name, request = case
    cell_mesh = _built_or_refused(engine, name, request)
    if cell_mesh is None:
        return
    table = cell_mesh.face_families
    if table is None:
        pytest.skip(f"{name}: no face family on this case, nothing to check")

    for index, family in enumerate(table.names):
        if family.startswith("boundary:"):
            assert np.all(table.cell_b[table.family == index] == -1), family


def test_the_four_sides_of_a_square_are_boundary_families(engine) -> None:
    request = square_case()
    cell_mesh = _built(engine, request)

    for side in SIDES:
        assert cell_mesh.face_rows(f"boundary:{side}").any(), f"no face on the {side} side"


# --------------------------------------------------------------------------- #
# Line families
# --------------------------------------------------------------------------- #


def _share_a_vertex(cell_mesh: PlanarCellMesh, first: int, second: int) -> bool:
    padded = cell_mesh.geometry.padded_connectivity
    return bool(set(padded[first][padded[first] >= 0]) & set(padded[second][padded[second] >= 0]))


def test_a_river_is_a_continuous_chain_of_cells(engine) -> None:
    cell_mesh = _built(engine, square_case())
    structured = type(engine).capabilities.structured
    chains = cell_mesh.chains("rivers")

    assert chains, "the river produced no chain"
    for chain in chains:
        assert chain.cell_ids.size >= 2
        for first, second in zip(chain.cell_ids[:-1], chain.cell_ids[1:], strict=True):
            if first == second:
                continue
            joined = int(second) in cell_mesh.geometry.neighbours(int(first))
            assert joined or (structured and _share_a_vertex(cell_mesh, int(first), int(second)))


def test_the_cells_of_a_river_stay_near_the_river(engine) -> None:
    cell_mesh = _built(engine, square_case())
    quality = cell_mesh.qa.families["rivers"]
    largest_cell_m = float(np.sqrt(cell_mesh.qa.area_quantiles_m2["max"]))

    assert quality["breaks"] == 0.0
    assert quality["max_line_offset_m"] <= 2.0 * largest_cell_m


def test_a_face_family_is_published_with_its_distance_to_the_line(engine) -> None:
    request = square_case()
    cell_mesh = _built(engine, request)
    extent_m = 1000.0
    quality = cell_mesh.qa.families["geology"]

    assert cell_mesh.face_rows("geology").any()
    assert "hausdorff_m" in quality
    assert quality["covered_length_rel"] >= 0.0
    if type(engine).capabilities.exact_faces:
        assert quality["hausdorff_m"] <= HAUSDORFF_RTOL * extent_m
        assert quality["covered_length_rel"] == pytest.approx(1.0, abs=HAUSDORFF_RTOL)


def test_a_face_family_names_the_zones_on_each_side(engine) -> None:
    cell_mesh = _built(engine, square_case())
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")

    assert {WEST_UNIT, EAST_UNIT} <= set(cell_mesh.zone_names)
    left = {cell_mesh.zone_names[z] for z in table.zone_left[rows] if z >= 0}
    right = {cell_mesh.zone_names[z] for z in table.zone_right[rows] if z >= 0}
    assert left <= {WEST_UNIT}
    assert right <= {EAST_UNIT}


# --------------------------------------------------------------------------- #
# Declarations
# --------------------------------------------------------------------------- #


def test_a_graded_engine_follows_the_size_ramp(engine) -> None:
    if not type(engine).capabilities.graded:
        pytest.skip("this engine does not grade its cells")
    cell_mesh = _built(engine, ramp_case())
    x = cell_mesh.centers[:, 0]
    areas = cell_mesh.geometry.areas

    assert areas[x > 400.0].mean() > 2.0 * areas[x < 100.0].mean()


def test_a_deterministic_engine_builds_the_same_mesh_twice(engine) -> None:
    if not type(engine).capabilities.deterministic:
        pytest.skip("this engine does not declare itself deterministic")
    request = square_case()
    first = _built(engine, request)
    np.random.seed(12345)
    random.seed(12345)
    second = _built(engine, request)

    np.testing.assert_array_equal(first.mesh.vertices, second.mesh.vertices)
    np.testing.assert_array_equal(first.connectivity_rows, second.connectivity_rows)
    np.testing.assert_array_equal(first.centers, second.centers)
    assert [chain.cell_ids.tolist() for chain in first.cell_chains] == [
        chain.cell_ids.tolist() for chain in second.cell_chains
    ]


def test_an_engine_that_uses_a_given_triangulation_keeps_its_cells(engine) -> None:
    request = given_triangulation_case()
    cell_mesh = _built_or_refused(engine, "given_triangulation", request)
    if cell_mesh is None:
        pytest.skip("this engine refuses a given triangulation by MeshRequestError")
    triangulation = request.input_triangulation
    cls = type(engine)

    if cls.capabilities.cell_types == (CellType.TRIANGLE,):
        assert cell_mesh.n_cells == len(triangulation.triangles)
    assert abs(cell_mesh.qa.area_sum_m2 - request.domain.area) <= AREA_RTOL * request.domain.area


def test_an_engine_refuses_a_request_it_cannot_honour_by_a_typed_error(engine) -> None:
    """A size finer than a structured engine can give is refused, never silently coarsened."""
    if not type(engine).capabilities.structured:
        pytest.skip("only a structured engine is bound to the DEM pitch")
    request = square_case()
    finer = MeshRequest(
        domain=request.domain,
        crs_wkt=request.crs_wkt,
        grid=request.grid,
        nominal_size_m=request.grid.dx / 2.0,
    )

    with pytest.raises(MeshRequestError):
        engine.build(finer)


def test_the_geometry_of_a_mesh_matches_the_polygon_of_the_island(engine) -> None:
    """The cells of an unstructured engine stay inside the island and cover all of it."""
    if type(engine).capabilities.structured:
        pytest.skip("a structured engine covers the DEM rectangle, not the domain")
    request = island_case()
    cell_mesh = _built(engine, request)
    union = shapely.union_all(cell_polygons(cell_mesh.mesh.vertices, cell_mesh.connectivity_rows))
    outside = union.difference(request.domain.buffer(1.0e-6 * 400.0))

    assert outside.area <= AREA_RTOL * request.domain.area
