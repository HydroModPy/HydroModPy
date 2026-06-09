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
    return SolverMesh(
        planar_mesh=mesh,
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
    sm = SolverMesh.from_structured_arrays(
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
    sm = SolverMesh.from_structured_arrays(
        nrow=1, ncol=2, top=np.zeros((1, 2)), botm=-np.ones((1, 1, 2)), inactive_mask=mask
    )
    assert sm.idomain().tolist() == [[1, 0]]


# -- Structured reshape + the structured-only guards --------------------------


def test_reshape_round_trip_on_non_square_structured_grid() -> None:
    sm = SolverMesh.from_structured_arrays(
        nrow=2, ncol=3, top=np.zeros((2, 3)), botm=np.zeros((1, 2, 3))
    )
    flat = np.arange(6, dtype=float)
    grid = sm.reshape_to_grid(flat)
    assert grid.shape == (2, 3)
    assert np.array_equal(sm.flatten_from_grid(grid), flat)


def test_structured_delr_delc_on_non_uniform_grid() -> None:
    sm = SolverMesh.from_structured_arrays(
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
    sm = SolverMesh.from_structured_arrays(
        nrow=2, ncol=2, top=np.zeros((2, 2)), botm=np.zeros((1, 2, 2))
    )
    kw = sm.to_disv_kwargs()
    for key in ("nvert", "ncpl", "vertices", "cell2d", "top", "botm"):
        assert key in kw
    assert kw["ncpl"] == 4


# -- __post_init__ invariant --------------------------------------------------


def test_post_init_rejects_wrong_top_size() -> None:
    mesh = _unstructured_two_quads().planar_mesh
    with pytest.raises(ValueError, match="top must have"):
        SolverMesh(
            planar_mesh=mesh,
            top=np.zeros(3),
            botm=np.zeros((1, 2)),
            inactive_mask=np.zeros((1, 2), bool),
        )


def test_post_init_rejects_mask_shape_mismatch() -> None:
    mesh = _unstructured_two_quads().planar_mesh
    with pytest.raises(ValueError, match="inactive_mask"):
        SolverMesh(
            planar_mesh=mesh,
            top=np.zeros(2),
            botm=np.zeros((2, 2)),
            inactive_mask=np.zeros((1, 2), bool),  # nlay mismatch vs botm
        )
