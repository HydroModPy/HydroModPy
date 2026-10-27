"""The triangle engine: centres the solvers read, the seed it records and what its QA says."""

from __future__ import annotations

import dataclasses
from importlib.util import find_spec

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from hydromodpy.spatial.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.spatial.mesh.gmsh_grid.exchange_api import load_planar_mesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh
from hydromodpy.spatial.mesh.request import InputTriangulation, LineFamilySpec, MeshRequest
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    bundle_msh,
    bundle_triangulation,
    grid_over,
    mesh_request,
    square_domain,
    uniform_size_field,
)

needs_gmsh = pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")

X0, Y0 = L93_ORIGIN
SQUARE = square_domain(1000.0, x0=X0, y0=Y0)
RIVER = LineString([(X0 + 100, Y0 + 150), (X0 + 450, Y0 + 420), (X0 + 900, Y0 + 880)])
BUNDLES = (
    "dupuit_circular_island_ocean_irregular_tri_radial_48",
    "stream_depletion_glover_balmer_tri_refined_well",
)


def _read_request(case: str) -> MeshRequest:
    """The triangles of a committed bundle, handed to the engine as a triangulation to read."""
    triangulation = bundle_triangulation(case)
    mesh = HydroMesh(
        vertices=triangulation.vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(triangulation.triangles)),),
    )
    domain = domain_polygon_from_mesh(mesh)
    return mesh_request(
        grid_over(domain), domain=domain, nominal_size_m=10.0, input_triangulation=triangulation
    )


def _generated_and_read() -> tuple[object, object]:
    """A sized square with a river, then its own triangles read back with the same river."""
    grid = grid_over(SQUARE, 25.0)
    request = mesh_request(
        grid,
        nominal_size_m=50.0,
        size_field=uniform_size_field(grid, 50.0),
        lines=(LineFamilySpec("rivers", "cell", (shapely.segmentize(RIVER, 50.0),)),),
    )
    generated = TriangleMeshEngine().build(request)
    triangulation = InputTriangulation(
        generated.mesh.vertices, np.asarray(generated.mesh.flat_connectivity), {}
    )
    read = TriangleMeshEngine().build(
        dataclasses.replace(request, input_triangulation=triangulation)
    )
    return generated, read


@pytest.mark.parametrize("case", BUNDLES)
def test_the_centres_are_the_vertex_means_of_the_planar_mesh_reader(case: str) -> None:
    cell_mesh = TriangleMeshEngine().build(_read_request(case))
    x, y = load_planar_mesh(bundle_msh(case)).cell_centroids()

    assert np.array_equal(cell_mesh.centers[:, 0], x)
    assert np.array_equal(cell_mesh.centers[:, 1], y)
    assert cell_mesh.center_kind == "vertex_mean"


@pytest.mark.parametrize("case", BUNDLES)
def test_a_read_triangulation_records_no_seed(case: str) -> None:
    assert TriangleMeshEngine().build(_read_request(case)).identity.seed is None


@needs_gmsh
def test_a_generated_triangulation_records_the_seed_gmsh_was_given() -> None:
    request = mesh_request(grid_over(SQUARE, 100.0), nominal_size_m=100.0, seed=7)

    assert TriangleMeshEngine().build(request).identity.seed == 7


@needs_gmsh
def test_a_read_triangulation_says_its_lines_were_not_embedded() -> None:
    generated, read = _generated_and_read()

    assert len(set(read.qa.notes) - set(generated.qa.notes)) == 1


@needs_gmsh
def test_a_generated_mesh_measures_its_cells_against_the_size_asked_and_a_read_one_does_not() -> (
    None
):
    generated, read = _generated_and_read()

    assert generated.qa.size_fidelity["p50"] > 0.0
    assert read.qa.size_fidelity == {}
