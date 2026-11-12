"""The triangle engine: centers the solvers read, the seed it records and what its QA says."""

from __future__ import annotations

import dataclasses
from importlib.util import find_spec

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from hydromodpy.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planning.input_triangulation import domain_polygon_from_mesh
from hydromodpy.mesh.request import InputTriangulation, LineFamilySpec, MeshRequest
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
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
def test_read_triangulation_has_no_seed(case: str) -> None:
    assert TriangleMeshEngine().build(_read_request(case)).identity.seed is None


@pytest.mark.parametrize("case", BUNDLES)
def test_area_closes_on_the_domain(case: str) -> None:
    request = _read_request(case)
    cell_mesh = TriangleMeshEngine().build(request)

    assert cell_mesh.qa.domain_area_m2 == request.domain.area
    assert cell_mesh.qa.area_sum_rel_error <= 1e-9


@needs_gmsh
def test_generated_triangulation_records_its_seed() -> None:
    request = mesh_request(grid_over(SQUARE, 100.0), nominal_size_m=100.0, seed=7)

    assert TriangleMeshEngine().build(request).identity.seed == 7


@needs_gmsh
def test_read_triangulation_notes_unembedded_lines() -> None:
    generated, read = _generated_and_read()

    (note,) = set(read.qa.notes) - set(generated.qa.notes)
    assert isinstance(note, str) and note


@needs_gmsh
def test_size_fidelity_only_when_generated() -> None:
    generated, read = _generated_and_read()

    assert generated.qa.size_fidelity["p50"] > 0.0
    assert read.qa.size_fidelity == {}
