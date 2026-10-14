"""The voronoi engine: generated generators, or the dual of a triangulation read."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.engines.voronoi.lloyd import LLOYD_TOLERANCE
from hydromodpy.spatial.mesh.gmsh_grid.exchange_api import load_planar_mesh
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import read_gmsh_2d_mesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import (
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
    SizeField,
)

WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 350_000.0, 6_780_000.0
HERE = Path(__file__).resolve().parent
BUNDLES = HERE.parents[3] / "validation_cases" / "shared" / "mesh_bundles"
GOLDEN = HERE / "voronoi" / "golden"

RIVER = LineString([(X0 + 100, Y0 + 150), (X0 + 450, Y0 + 420), (X0 + 900, Y0 + 880)])
CONTACT = LineString([(X0 + 400, Y0), (X0 + 600, Y0 + 1000)])


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


def _square(size: float = 40.0, **options) -> MeshRequest:
    """A 1 km square with a river and a contact, resampled on a constant size field."""
    domain = box(X0, Y0, X0 + 1000, Y0 + 1000)
    grid = _grid(*domain.bounds, n=50)
    field = SizeField(np.full((grid.nrow, grid.ncol), size), grid)
    families = (
        LineFamilySpec("rivers", "cell", (RIVER,)),
        LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)),
    )
    return MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=grid,
        nominal_size_m=size,
        lines=resample_families(families, domain=domain, size_field=field).families,
        size_field=field,
        options=options,
    )


def _read(bundle: str, **options) -> MeshRequest:
    data = read_gmsh_2d_mesh(BUNDLES / bundle / "mesh_2d.msh")
    triangulation = load_planar_mesh(BUNDLES / bundle / "mesh_2d.msh").to_hydro_mesh()
    domain = domain_polygon_from_mesh(triangulation)
    return MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=_grid(*domain.bounds),
        nominal_size_m=10.0,
        input_triangulation=InputTriangulation(data.points_xy, data.connectivity, {}),
        options=options,
    )


def _lattice(river: bool = True, contact: bool = True) -> MeshRequest:
    """A 1 km square triangulated on a 10 x 11 lattice, its river and contact on lattice edges.

    The columns are wider east of the contact, so the triangles around a vertex of the
    contact lie mostly on its west side: the vote that gives a cell its side has no tie.
    """
    xs = np.array([0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 620.0, 740.0, 860.0, 1000.0])
    ys = np.linspace(0.0, 1000.0, 11)
    vertices = np.array([(X0 + x, Y0 + y) for y in ys for x in xs])
    width = len(xs)
    triangles = []
    for j in range(len(ys) - 1):
        for i in range(width - 1):
            n00, n10 = j * width + i, j * width + i + 1
            n01, n11 = (j + 1) * width + i, (j + 1) * width + i + 1
            triangles += [(n00, n10, n11), (n00, n11, n01)]
    lines = []
    if river:
        lines.append(
            LineFamilySpec("rivers", "cell", (LineString([(X0, Y0 + 300), (X0 + 1000, Y0 + 300)]),))
        )
    if contact:
        lines.append(
            LineFamilySpec(
                "geology",
                "face",
                (LineString([(X0 + 500, Y0), (X0 + 500, Y0 + 1000)]),),
                ("west_unit",),
                ("east_unit",),
            )
        )
    domain = box(X0, Y0, X0 + 1000, Y0 + 1000)
    return MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=_grid(*domain.bounds),
        nominal_size_m=100.0,
        lines=tuple(lines),
        input_triangulation=InputTriangulation(vertices, np.array(triangles), {}),
    )


@pytest.mark.parametrize(
    "bundle",
    [
        "dupuit_circular_island_ocean_irregular_tri_radial_48",
        "stream_depletion_glover_balmer_tri_refined_well",
    ],
)
def test_the_dual_of_a_triangulation_keeps_the_faces_of_the_old_dual(bundle: str) -> None:
    """The golden froze the dual of c710a26a5 (Qhull, 1 mm rounding): same faces, areas to 1e-5."""
    golden = np.load(GOLDEN / f"old_dual_{bundle}.npz")
    cell_mesh = VoronoiMeshEngine().build(_read(bundle, seeds="triangulation"))

    geometry = cell_mesh.geometry
    faces = np.ascontiguousarray(geometry.edge_cells[geometry.edge_cells[:, 1] >= 0])
    faces = faces[np.lexsort((faces[:, 1], faces[:, 0]))].astype(np.int64)
    assert len(faces) == int(golden["n_faces"])
    assert hashlib.sha256(faces.tobytes()).hexdigest() == str(golden["faces_sha256"])
    assert np.allclose(geometry.areas, golden["areas"], rtol=1e-5, atol=0.0)
    assert cell_mesh.center_kind == "generator"
    assert cell_mesh.identity.seed is None


def test_the_generators_of_a_triangulation_are_the_centres_to_the_bit() -> None:
    request = _read("stream_depletion_glover_balmer_tri_refined_well")
    cell_mesh = VoronoiMeshEngine().build(request)

    assert np.array_equal(cell_mesh.centers, request.input_triangulation.vertices)
    assert np.array_equal(
        cell_mesh.mesh.cell_data["disv_cell_center"], request.input_triangulation.vertices
    )
    assert cell_mesh.qa.extras["boundary_seeds_added"] == 0.0


def test_the_registry_serves_the_voronoi_engine() -> None:
    assert type(registry.create("voronoi")) is VoronoiMeshEngine


def test_a_lattice_river_is_a_chain_and_its_faces_are_the_dual_faces_it_crosses() -> None:
    cell_mesh = VoronoiMeshEngine().build(_lattice(contact=False))

    (chain,) = cell_mesh.chains("rivers")
    assert len(chain.cell_ids) == 10
    assert np.allclose(cell_mesh.centers[chain.cell_ids, 1], Y0 + 300.0)
    rows = cell_mesh.face_rows("rivers")
    table = cell_mesh.face_families
    inside = rows & (table.cell_b >= 0)
    pairs = {tuple(sorted(p)) for p in zip(table.cell_a[inside], table.cell_b[inside], strict=True)}
    assert pairs == {
        tuple(sorted(p)) for p in zip(chain.cell_ids[:-1], chain.cell_ids[1:], strict=True)
    }
    # The two river ends lie on the west and east sides: the faces they touch there are rows too.
    ends = rows & (table.cell_b < 0)
    assert set(table.cell_a[ends].tolist()) == {int(chain.cell_ids[0]), int(chain.cell_ids[-1])}
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0


def test_a_contact_of_a_triangulation_becomes_a_staircase_that_names_its_zones() -> None:
    cell_mesh = VoronoiMeshEngine().build(_lattice(river=False))
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")
    names = np.asarray(cell_mesh.zone_names)

    assert rows.sum() > 0
    assert set(names[table.zone_left[rows]]) == {"west_unit"}
    assert set(names[table.zone_right[rows]]) == {"east_unit"}
    start = cell_mesh.mesh.vertices[table.node_a[rows]]
    face = cell_mesh.mesh.vertices[table.node_b[rows]] - start
    reach = cell_mesh.geometry.area_centroids[table.cell_a[rows]] - start
    assert np.all(face[:, 0] * reach[:, 1] - face[:, 1] * reach[:, 0] > 0.0)
    assert any("staircase" in note for note in cell_mesh.qa.notes)


def test_a_dual_gives_no_cell_zone_and_no_lake_staircase_to_the_readers_of_exact_faces() -> None:
    """The engine declares exact faces; a staircase is not, so the dual keeps what it published."""
    request = _lattice(river=False)
    shore = LineString([(X0 + 200, Y0 + 200), (X0 + 800, Y0 + 200), (X0 + 800, Y0 + 800)])
    lakes = LineFamilySpec("lakes", "face", (shore,))
    request = MeshRequest(
        domain=request.domain,
        crs_wkt=WKT,
        grid=request.grid,
        nominal_size_m=request.nominal_size_m,
        lines=(*request.lines, lakes),
        input_triangulation=request.input_triangulation,
    )
    cell_mesh = VoronoiMeshEngine().build(request)

    assert cell_mesh.face_rows("geology").any()
    assert cell_mesh.cell_zone is None
    assert not cell_mesh.face_rows("lakes").any()


def test_the_sides_of_a_triangulation_keep_the_faces_of_the_cells_centred_on_them() -> None:
    cell_mesh = VoronoiMeshEngine().build(_lattice(river=False, contact=False))
    west = cell_mesh.face_rows("boundary:west")
    table = cell_mesh.face_families

    assert west.sum() == 11
    assert np.allclose(cell_mesh.centers[table.cell_a[west], 0], X0)


def test_the_generated_river_chain_runs_on_the_river() -> None:
    cell_mesh = VoronoiMeshEngine().build(_square())

    (chain,) = cell_mesh.chains("rivers")
    on_river = shapely.distance(shapely.points(cell_mesh.centers[chain.cell_ids]), RIVER) < 1e-6
    assert on_river.mean() > 0.9
    for first, second in zip(chain.cell_ids[:-1], chain.cell_ids[1:], strict=True):
        assert second in cell_mesh.geometry.neighbours(first)
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0
    assert chain.offset_m is not None
    assert cell_mesh.qa.families["rivers"]["crossings"] == 1.0


def test_a_generated_contact_is_a_row_of_faces_between_mirror_pairs() -> None:
    cell_mesh = VoronoiMeshEngine().build(_square())
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")
    names = np.asarray(cell_mesh.zone_names)
    stats = cell_mesh.qa.families["geology"]

    assert set(names[table.zone_left[rows]]) == {"west_unit"}
    assert set(names[table.zone_right[rows]]) == {"east_unit"}
    assert stats["conformal_length_share"] > 0.9
    assert stats["covered_length_rel"] > 0.9
    assert stats["mirror_pairs"] > 0
    assert stats["mixed_cells"] <= stats["yielded_segments"] + 1
    start = cell_mesh.mesh.vertices[table.node_a[rows]]
    face = cell_mesh.mesh.vertices[table.node_b[rows]] - start
    reach = cell_mesh.geometry.area_centroids[table.cell_a[rows]] - start
    assert np.all(face[:, 0] * reach[:, 1] - face[:, 1] * reach[:, 0] > 0.0)


def test_a_generated_side_row_runs_with_its_cell_on_the_left() -> None:
    cell_mesh = VoronoiMeshEngine().build(_square())
    table = cell_mesh.face_families
    rows = np.flatnonzero(
        np.isin(table.family, [i for i, n in enumerate(table.names) if n.startswith("boundary:")])
    )
    start = cell_mesh.mesh.vertices[table.node_a[rows]]
    face = cell_mesh.mesh.vertices[table.node_b[rows]] - start
    reach = cell_mesh.geometry.area_centroids[table.cell_a[rows]] - start

    assert rows.size > 0
    assert np.all(face[:, 0] * reach[:, 1] - face[:, 1] * reach[:, 0] > 0.0)
    assert np.all(table.cell_b[rows] == -1)


def test_the_identity_names_the_engine_the_request_and_its_seed() -> None:
    request = _square()
    cell_mesh = VoronoiMeshEngine().build(request)

    assert cell_mesh.identity.engine_id == "voronoi"
    assert cell_mesh.identity.engine_version == "2.0.0"
    assert cell_mesh.identity.request_hash == request.canonical_hash()
    assert cell_mesh.identity.seed == request.seed
    assert cell_mesh.qa.declarations == VoronoiMeshEngine.capabilities.declarations()
    assert cell_mesh.qa.area_sum_rel_error <= 1e-9


def test_one_request_gives_one_mesh_and_the_global_random_state_is_not_read() -> None:
    request = _square(size=60.0)
    first = VoronoiMeshEngine().build(request)
    np.random.seed(7)
    second = VoronoiMeshEngine().build(request)

    assert np.array_equal(first.mesh.vertices, second.mesh.vertices)
    assert np.array_equal(first.centers, second.centers)
    assert first.qa.as_dict() == second.qa.as_dict()


def test_another_seed_moves_the_free_seeds_and_keeps_the_cell_count() -> None:
    base = _square(size=60.0)
    other = MeshRequest(
        domain=base.domain,
        crs_wkt=WKT,
        grid=base.grid,
        nominal_size_m=base.nominal_size_m,
        lines=base.lines,
        size_field=base.size_field,
        seed=1,
    )
    first = VoronoiMeshEngine().build(base)
    second = VoronoiMeshEngine().build(other)

    assert first.n_cells == second.n_cells
    assert not np.array_equal(first.centers, second.centers)
    assert second.identity.seed == 1


def test_the_qa_reports_the_relaxation_the_seeds_and_the_libraries() -> None:
    cell_mesh = VoronoiMeshEngine().build(_square(size=60.0))
    extras = cell_mesh.qa.extras

    for key in (
        "lloyd_iterations",
        "lloyd_cap",
        "lloyd_converged",
        "lloyd_move_p50",
        "lloyd_move_max",
        "n_seeds_free",
        "n_seeds_chain",
        "n_seeds_mirror",
        "n_seeds_boundary",
        "boundary_seeds_added",
        "origin_x",
        "origin_y",
    ):
        assert key in extras, key
    assert extras["origin_x"] == X0 and extras["origin_y"] == Y0
    assert cell_mesh.qa.size_fidelity["p50"] == pytest.approx(1.0, abs=0.1)
    assert any("reproducible with" in note and "geos" in note for note in cell_mesh.qa.notes)


def test_the_lloyd_tolerance_of_the_request_stops_the_relaxation() -> None:
    loose = VoronoiMeshEngine().build(_square(size=60.0, lloyd_tolerance=1.0)).qa.extras
    default = VoronoiMeshEngine().build(_square(size=60.0)).qa.extras

    assert loose["lloyd_iterations"] == 1.0
    assert loose["lloyd_converged"] == 1.0
    assert default["lloyd_iterations"] > 1.0
    assert default["lloyd_cap"] == 25.0
    assert LLOYD_TOLERANCE == 0.01


def test_a_request_without_a_size_field_is_meshed_at_its_nominal_size() -> None:
    domain = box(X0, Y0, X0 + 400, Y0 + 400)
    request = MeshRequest(
        domain=domain, crs_wkt=WKT, grid=_grid(*domain.bounds, n=20), nominal_size_m=40.0
    )
    cell_mesh = VoronoiMeshEngine().build(request)

    assert 80 <= cell_mesh.n_cells <= 120
    assert cell_mesh.qa.area_sum_rel_error <= 1e-9
    assert cell_mesh.identity.request_hash == request.canonical_hash()


def test_triangulation_seeds_need_a_triangulation() -> None:
    with pytest.raises(MeshRequestError, match="needs an input triangulation"):
        VoronoiMeshEngine().build(_square(seeds="triangulation"))


def test_generated_seeds_refuse_a_triangulation_to_read() -> None:
    request = _read("dupuit_circular_island_ocean_irregular_tri_radial_48", seeds="generated")
    with pytest.raises(MeshRequestError, match="also carries a triangulation to read"):
        VoronoiMeshEngine().build(request)


def test_an_unknown_seed_source_is_refused() -> None:
    with pytest.raises(MeshRequestError, match="unknown voronoi seeds"):
        VoronoiMeshEngine().build(_square(seeds="lloyd"))
