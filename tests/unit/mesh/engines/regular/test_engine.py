"""The regular engine: cells on the DEM grid, centers the solvers read, and what its QA says."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.cells.boundary import SIDE_OFFSET_KEY
from hydromodpy.mesh.engines.regular.engine import _SIDE_STATEMENT, RegularMeshEngine
from hydromodpy.mesh.engines.regular.grid import plan_layout
from hydromodpy.mesh.request import InputTriangulation
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec, mesh_request, uniform_size_field

DEM = grid_spec(12, 20, 50.0, crs_wkt=LAMBERT93_WKT)
"""A 1 km by 600 m DEM at 50 m."""


def test_the_centers_equal_the_vertex_mean_the_solvers_read(dem_grid) -> None:
    request = mesh_request(dem_grid, nominal_size_m=max(dem_grid.dx, dem_grid.dy))
    cell_mesh = RegularMeshEngine().build(request)
    x, y = cell_mesh.mesh.cell_centroids()

    np.testing.assert_array_equal(cell_mesh.centers[:, 0], x)
    np.testing.assert_array_equal(cell_mesh.centers[:, 1], y)
    assert cell_mesh.center_kind == "cell_center"


@pytest.mark.parametrize("size", [DEM.dx, 130.0], ids=["dem_pitch", "coarser"])
def test_the_quality_report_gives_the_pitch_of_the_grid(size: float) -> None:
    layout = plan_layout(DEM, size, {})
    cell_mesh = RegularMeshEngine().build(mesh_request(DEM, nominal_size_m=size))

    assert cell_mesh.qa.extras["dx_m"] == layout.dx
    assert cell_mesh.qa.extras["dy_m"] == layout.dy


def test_the_shape_option_of_the_request_reaches_the_grid() -> None:
    cell_mesh = RegularMeshEngine().build(mesh_request(DEM, options={"shape": [3, 7]}))

    assert cell_mesh.structured_shape == (3, 7)


def test_a_side_head_sits_half_a_cell_inside_and_the_quality_report_says_so() -> None:
    cell_mesh = RegularMeshEngine().build(mesh_request(DEM))

    assert _SIDE_STATEMENT in cell_mesh.qa.notes
    assert cell_mesh.qa.extras[SIDE_OFFSET_KEY] == 0.5 * DEM.dx


def test_a_resampled_grid_says_so_in_its_quality_report() -> None:
    native = RegularMeshEngine().build(mesh_request(DEM))
    coarse = RegularMeshEngine().build(mesh_request(DEM, nominal_size_m=130.0))
    shape = coarse.structured_shape

    (note,) = set(coarse.qa.notes) - set(native.qa.notes)
    assert f"{shape[0]} x {shape[1]}" in note


def test_the_size_field_is_ignored_and_the_quality_report_says_so() -> None:
    plain = RegularMeshEngine().build(mesh_request(DEM))
    graded = RegularMeshEngine().build(mesh_request(DEM, size_field=uniform_size_field(DEM, 80.0)))

    np.testing.assert_array_equal(plain.mesh.vertices, graded.mesh.vertices)
    (note,) = set(graded.qa.notes) - set(plain.qa.notes)
    assert isinstance(note, str) and note


def test_the_regular_grid_draws_nothing_at_random_and_records_no_seed() -> None:
    assert RegularMeshEngine().build(mesh_request(DEM, seed=7)).identity.seed is None


def test_an_input_triangulation_is_refused() -> None:
    triangulation = InputTriangulation(
        np.array([[0.0, 0.0], [1000.0, 0.0], [0.0, 600.0]]), np.array([[0, 1, 2]]), {}
    )
    request = mesh_request(DEM, input_triangulation=triangulation)

    with pytest.raises(MeshRequestError, match="cannot use an input triangulation"):
        RegularMeshEngine().build(request)
