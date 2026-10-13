"""Contract tests for SolverMesh, the central solver-facing grid object.

The whole solver pipeline depends on SolverMesh, so its public contract is owned
here: geometry helpers (areas, centroids, thicknesses, idomain), the
structured/unstructured split (reshape vs the structured-only raising members),
the DIS/DISV exports, and the __post_init__ prismatic invariant.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from tests._helpers.solver_meshes import solver_mesh_from, solver_mesh_from_structured_arrays


def _unstructured_two_quads() -> SolverMesh:
    """Two side-by-side quads as an UNSTRUCTURED mesh (structured_shape=None)."""
    verts = np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]], dtype=float
    )
    conn = np.array([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int)
    mesh = HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),),
        structured_shape=None,
    )
    return solver_mesh_from(
        mesh,
        top=np.full(2, 10.0),
        botm=np.zeros((1, 2)),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )


# -- Geometry -----------------------------------------------------------------


def test_cell_areas_shoelace_is_winding_invariant() -> None:
    # A unit square and a 2x1 rectangle, regardless of node winding.
    sm = _unstructured_two_quads()
    areas = sm.cell_areas()
    assert areas[0] == pytest.approx(1.0)
    assert areas[1] == pytest.approx(1.0)
    # characteristic_length = sqrt(mean area) = 1.0 here.
    assert sm.characteristic_length == pytest.approx(1.0)


def test_cell_centroids_are_vertex_means() -> None:
    sm = _unstructured_two_quads()
    centroids = sm.cell_centroids()
    assert centroids[0] == pytest.approx([0.5, 0.5])
    assert centroids[1] == pytest.approx([1.5, 0.5])


def test_layer_thicknesses_and_center_depths() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=2,
        top=np.array([[10.0, 10.0]]),
        botm=np.array([[[6.0, 6.0]], [[0.0, 0.0]]]),  # (nlay=2, 1, 2)
    )
    thick = sm.layer_thicknesses()
    assert thick.shape == (2, 2)
    assert thick[0] == pytest.approx([4.0, 4.0])  # 10 -> 6
    assert thick[1] == pytest.approx([6.0, 6.0])  # 6 -> 0
    depths = sm.layer_center_depths()
    assert depths[0] == pytest.approx([2.0, 2.0])  # top(10) - center(8)
    assert depths[1] == pytest.approx([7.0, 7.0])  # top(10) - center(3)


def test_idomain_from_inactive_mask() -> None:
    mask = np.array([[False, True]])
    sm = solver_mesh_from_structured_arrays(
        nrow=1, ncol=2, top=np.zeros((1, 2)), botm=-np.ones((1, 1, 2)), inactive_mask=mask
    )
    assert sm.idomain().tolist() == [[1, 0]]


def test_structured_arrays_put_row_0_at_the_north_like_modflow() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=3,
        ncol=2,
        top=np.zeros((3, 2)),
        botm=-np.ones((1, 3, 2)),
        dx=10.0,
        dy=5.0,
        xoff=100.0,
        yoff=200.0,
    )
    centroids = sm.cell_centroids().reshape(3, 2, 2)
    assert centroids[:, 0, 1] == pytest.approx([212.5, 207.5, 202.5])
    assert centroids[0, :, 0] == pytest.approx([105.0, 115.0])
    assert sm.yoffset == pytest.approx(200.0)
    assert sm.yvertices[:, 0] == pytest.approx([215.0, 210.0, 205.0, 200.0])


# -- Structured reshape + the structured-only guards --------------------------


def test_reshape_round_trip_on_non_square_structured_grid() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=np.zeros((2, 3)), botm=np.zeros((1, 2, 3))
    )
    flat = np.arange(6, dtype=float)
    grid = sm.reshape_to_grid(flat)
    assert grid.shape == (2, 3)
    assert np.array_equal(sm.flatten_from_grid(grid), flat)


def test_structured_delr_delc_on_non_uniform_grid() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=2, ncol=2, top=np.zeros((2, 2)), botm=np.zeros((1, 2, 2)), dx=5.0, dy=7.0
    )
    delr, delc = sm.structured_delr_delc()
    assert delr.tolist() == pytest.approx([5.0, 5.0])
    assert delc.tolist() == pytest.approx([7.0, 7.0])
    assert sm.nrow == 2 and sm.ncol == 2


def test_structured_only_members_raise_on_unstructured() -> None:
    sm = _unstructured_two_quads()
    assert sm.is_structured is False
    assert sm.structured_shape is None
    for accessor in (
        lambda: sm.nrow,
        lambda: sm.ncol,
        lambda: sm.delr,
        lambda: sm.delc,
        lambda: sm.xvertices,
        lambda: sm.yvertices,
        lambda: sm.structured_delr_delc(),
        lambda: sm.to_dis_kwargs(),
    ):
        with pytest.raises(ValueError):
            accessor()


def test_reshape_is_identity_on_unstructured() -> None:
    sm = _unstructured_two_quads()
    flat = np.array([1.0, 2.0])
    assert np.array_equal(sm.reshape_to_grid(flat), flat)
    assert np.array_equal(sm.flatten_from_grid(flat), flat)


# -- DISV export --------------------------------------------------------------


def test_to_disv_kwargs_has_the_expected_keys() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=2, ncol=2, top=np.zeros((2, 2)), botm=np.zeros((1, 2, 2))
    )
    kw = sm.to_disv_kwargs()
    for key in ("nvert", "ncpl", "vertices", "cell2d", "top", "botm"):
        assert key in kw
    assert kw["ncpl"] == 4


# -- __post_init__ invariant --------------------------------------------------


def test_post_init_rejects_wrong_top_size() -> None:
    cell_mesh = _unstructured_two_quads().cell_mesh
    with pytest.raises(ValueError, match="top must have"):
        SolverMesh(
            cell_mesh=cell_mesh,
            top=np.zeros(3),
            botm=np.zeros((1, 2)),
            inactive_mask=np.zeros((1, 2), bool),
        )


def test_post_init_rejects_mask_shape_mismatch() -> None:
    cell_mesh = _unstructured_two_quads().cell_mesh
    with pytest.raises(ValueError, match="inactive_mask"):
        SolverMesh(
            cell_mesh=cell_mesh,
            top=np.zeros(2),
            botm=np.zeros((2, 2)),
            inactive_mask=np.zeros((1, 2), bool),  # nlay mismatch vs botm
        )


# -- Reads the cell mesh ------------------------------------------------------


def test_centres_and_areas_are_those_of_the_cell_mesh() -> None:
    sm = _unstructured_two_quads()
    assert np.array_equal(sm.cell_centroids(), sm.cell_mesh.centers)
    assert np.array_equal(sm.cell_areas(), sm.cell_mesh.geometry.areas)
    assert sm.planar_mesh is sm.cell_mesh.mesh


def test_centres_and_areas_are_copies() -> None:
    sm = _unstructured_two_quads()
    sm.cell_centroids()[:] = -1.0
    sm.cell_areas()[:] = -1.0
    assert np.all(sm.cell_mesh.centers >= 0.0)
    assert np.all(sm.cell_mesh.geometry.areas > 0.0)


def test_face_adjacency_is_the_shared_face_graph_and_may_be_modified() -> None:
    sm = _unstructured_two_quads()
    adjacency = sm.face_adjacency()
    assert adjacency == [{1}, {0}]
    adjacency[0].add(7)
    assert sm.face_adjacency() == [{1}, {0}]


def test_face_adjacency_of_a_grid_has_no_diagonal() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=3, ncol=3, top=np.zeros((3, 3)), botm=-np.ones((1, 3, 3))
    )
    adjacency = sm.face_adjacency()
    assert adjacency[4] == {1, 3, 5, 7}
    assert adjacency[0] == {1, 3}


def test_layer_center_depths_are_never_negative() -> None:
    # A cell whose bottom lies above its top (a nodata-like inversion) has no depth below zero.
    sm = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=2,
        top=np.array([[10.0, 10.0]]),
        botm=np.array([[[6.0, 12.0]], [[0.0, 14.0]]]),
    )
    assert (sm.layer_center_depths() >= 0.0).all()
    assert sm.layer_center_depths()[0, 0] == pytest.approx(2.0)


def test_a_grid_from_arrays_is_a_regular_cell_mesh_in_a_local_frame() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=np.zeros((2, 3)), botm=-np.ones((1, 2, 3)), dx=10.0, dy=5.0
    )
    assert sm.cell_mesh.structured_shape == (2, 3)
    assert sm.cell_mesh.center_kind == "cell_center"
    assert sm.cell_mesh.crs_wkt
    assert sm.cell_areas() == pytest.approx(np.full(6, 50.0))
