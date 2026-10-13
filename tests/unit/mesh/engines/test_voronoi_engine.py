"""The voronoi engine is the production dual of its triangulation, with families carried over."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine, generator_cells
from hydromodpy.spatial.mesh.gmsh_grid.exchange_api import load_planar_mesh
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import read_gmsh_2d_mesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh, voronoi_dual_of_mesh
from hydromodpy.spatial.mesh.request import (
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
)

WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 350_000.0, 6_780_000.0
BUNDLES = Path(__file__).resolve().parents[4] / "validation_cases" / "shared" / "mesh_bundles"

needs_gmsh = pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")

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


def _square(**options) -> MeshRequest:
    domain = box(X0, Y0, X0 + 1000, Y0 + 1000)
    return MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=_grid(*domain.bounds),
        nominal_size_m=40.0,
        lines=(
            LineFamilySpec("rivers", "cell", (RIVER,)),
            LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)),
        ),
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


@pytest.mark.parametrize(
    "bundle",
    [
        "dupuit_circular_island_ocean_irregular_tri_radial_48",
        "stream_depletion_glover_balmer_tri_refined_well",
    ],
)
def test_the_dual_is_the_production_dual_bit_for_bit(bundle: str) -> None:
    triangulation = load_planar_mesh(BUNDLES / bundle / "mesh_2d.msh").to_hydro_mesh()
    production = voronoi_dual_of_mesh(triangulation, domain_polygon_from_mesh(triangulation))
    cell_mesh = VoronoiMeshEngine().build(_read(bundle, seeds="triangulation"))

    assert np.array_equal(cell_mesh.mesh.vertices, production.vertices)
    assert len(cell_mesh.mesh.flat_connectivity) == len(production.flat_connectivity)
    for ours, theirs in zip(
        cell_mesh.mesh.flat_connectivity, production.flat_connectivity, strict=True
    ):
        assert np.array_equal(ours, theirs)
    assert np.array_equal(cell_mesh.centers, production.cell_data["disv_cell_center"])
    assert np.array_equal(
        cell_mesh.mesh.cell_data["disv_cell_center"], production.cell_data["disv_cell_center"]
    )
    assert cell_mesh.center_kind == "generator"
    assert cell_mesh.identity.seed is None


@needs_gmsh
def test_the_registry_serves_the_voronoi_engine() -> None:
    assert type(registry.create("voronoi")) is VoronoiMeshEngine


@needs_gmsh
def test_a_river_chain_is_the_cells_of_the_river_vertices() -> None:
    cell_mesh = VoronoiMeshEngine().build(_square())
    (chain,) = cell_mesh.chains("rivers")
    on_river = shapely.distance(shapely.points(cell_mesh.centers[chain.cell_ids]), RIVER) < 1e-6

    assert on_river.mean() > 0.9
    for first, second in zip(chain.cell_ids[:-1], chain.cell_ids[1:], strict=True):
        assert second in cell_mesh.geometry.neighbours(first)
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0


@needs_gmsh
def test_a_contact_becomes_a_staircase_that_names_its_zones() -> None:
    request = _square()
    cell_mesh = VoronoiMeshEngine().build(request)
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")
    names = np.asarray(cell_mesh.zone_names)

    assert rows.sum() > 0
    assert set(names[table.zone_left[rows]]) == {"west_unit"}
    assert set(names[table.zone_right[rows]]) == {"east_unit"}
    assert np.all(cell_mesh.cell_zone[table.cell_a[rows]] == table.zone_left[rows])
    assert np.all(cell_mesh.cell_zone[table.cell_b[rows]] == table.zone_right[rows])
    start = cell_mesh.mesh.vertices[table.node_a[rows]]
    face = cell_mesh.mesh.vertices[table.node_b[rows]] - start
    reach = cell_mesh.geometry.area_centroids[table.cell_a[rows]] - start
    assert np.all(face[:, 0] * reach[:, 1] - face[:, 1] * reach[:, 0] > 0.0)
    largest = float(np.sqrt(cell_mesh.qa.area_quantiles_m2["max"]))
    assert cell_mesh.qa.families["geology"]["hausdorff_m"] <= largest
    assert not VoronoiMeshEngine.capabilities.exact_faces
    assert any("staircase" in note for note in cell_mesh.qa.notes)


@needs_gmsh
def test_the_identity_names_the_engine_the_request_and_its_seed() -> None:
    request = _square()
    cell_mesh = VoronoiMeshEngine().build(request)

    assert cell_mesh.identity.engine_id == "voronoi"
    assert cell_mesh.identity.request_hash == request.canonical_hash()
    assert cell_mesh.identity.seed == request.seed
    assert cell_mesh.qa.declarations == VoronoiMeshEngine.capabilities.declarations()
    assert cell_mesh.qa.area_sum_rel_error <= 1e-9


def test_triangulation_seeds_need_a_triangulation() -> None:
    with pytest.raises(MeshRequestError, match="needs an input triangulation"):
        VoronoiMeshEngine().build(_square(seeds="triangulation"))


def test_generated_seeds_refuse_a_triangulation_to_read() -> None:
    request = _read("dupuit_circular_island_ocean_irregular_tri_radial_48", seeds="generated")
    with pytest.raises(MeshRequestError, match="also carries one to read"):
        VoronoiMeshEngine().build(request)


def test_an_unknown_seed_source_is_refused() -> None:
    with pytest.raises(MeshRequestError, match="unknown voronoi seeds"):
        VoronoiMeshEngine().build(_square(seeds="lloyd"))


def test_a_generator_clipped_away_has_no_cell() -> None:
    generators = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]])
    centers = generators[[0, 2, 3]]

    assert generator_cells(generators, centers).tolist() == [0, -1, 1, 2]


def test_a_split_cell_keeps_the_one_generator_left_between_its_neighbours() -> None:
    generators = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0], [4.0, 0.0]])
    centers = np.array([[0.0, 0.0], [1.0, 0.4], [2.0, 0.0], [3.0, 0.0]])

    assert generator_cells(generators, centers).tolist() == [0, 1, 2, 3, -1]


def test_a_split_cell_between_two_free_generators_stays_unmatched() -> None:
    generators = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]])
    centers = np.array([[0.0, 0.0], [1.0, 0.4], [3.0, 0.0]])

    assert generator_cells(generators, centers).tolist() == [0, -1, -1, 2]
