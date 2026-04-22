from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.utils.mesh.gmsh_grid import ExtrudedPrismMesh3D, GmshPlanarMesh2D


def _build_triangle_planar_mesh() -> GmshPlanarMesh2D:
    return GmshPlanarMesh2D(
        points_xy=np.array(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        connectivity=np.array([[0, 1, 2], [0, 2, 3]], dtype=int),
        cell_type="triangle",
    )


def test_extruded_triangle_mesh_counts_bounds_and_mapping():
    mesh_2d = _build_triangle_planar_mesh()
    mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
        mesh_2d,
        top_z=10.0,
        layer_thicknesses=[2.0, 3.0],
    )

    assert mesh_3d.kind == "extruded_prism_3d"
    assert mesh_3d.cell_type_2d == "triangle"
    assert mesh_3d.cell_type_3d == "triangular_prism"
    assert mesh_3d.n_layers == 2
    assert mesh_3d.n_nodes == 12
    assert mesh_3d.n_prisms == 4
    assert mesh_3d.shape == (2, 2)
    assert mesh_3d.bounds == (0.0, 0.0, 5.0, 1.0, 1.0, 10.0)
    assert np.allclose(mesh_3d.z_interfaces, np.array([10.0, 8.0, 5.0], dtype=float))
    assert np.allclose(mesh_3d.layer_centers_z, np.array([9.0, 6.5], dtype=float))

    assert np.array_equal(mesh_3d.layer_indices, np.array([0, 0, 1, 1], dtype=int))
    assert np.array_equal(mesh_3d.source_cell_indices, np.array([0, 1, 0, 1], dtype=int))
    assert np.array_equal(mesh_3d.prism_connectivity[0], np.array([0, 1, 2, 4, 5, 6], dtype=int))
    assert np.array_equal(mesh_3d.prism_connectivity[2], np.array([4, 5, 6, 8, 9, 10], dtype=int))

    prisms = mesh_3d.prisms
    assert len(prisms) == 4
    assert prisms[0].layer_index == 0
    assert prisms[0].source_cell_index == 0
    assert np.allclose(prisms[0].centroid, (2.0 / 3.0, 1.0 / 3.0, 9.0))


def test_extruded_quad_mesh_supports_explicit_z_interfaces():
    mesh_2d = GmshPlanarMesh2D(
        points_xy=np.array(
            [
                [10.0, 30.0],
                [20.0, 30.0],
                [20.0, 50.0],
                [10.0, 50.0],
            ],
            dtype=float,
        ),
        connectivity=np.array([[0, 1, 2, 3]], dtype=int),
        cell_type="quadrilateral",
    )

    mesh_3d = ExtrudedPrismMesh3D.from_planar_mesh(
        mesh_2d,
        z_interfaces=[100.0, 90.0, 70.0],
    )

    assert mesh_3d.cell_type_2d == "quadrilateral"
    assert mesh_3d.cell_type_3d == "quadrilateral_prism"
    assert mesh_3d.n_layers == 2
    assert mesh_3d.n_prisms == 2
    assert mesh_3d.prism_connectivity.shape == (2, 8)
    assert mesh_3d.bounds == (10.0, 30.0, 70.0, 20.0, 50.0, 100.0)


def test_extruded_prism_mesh_roundtrip_vtu_if_meshio_available():
    pytest.importorskip("meshio")

    mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
        _build_triangle_planar_mesh(),
        top_z=12.0,
        layer_thicknesses=[4.0, 6.0],
    )

    output_dir = Path.cwd() / "scratch_tests" / "extruded_prism_mesh" / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "extruded_reference.vtu"
    mesh_3d.to_file(path)
    reread = ExtrudedPrismMesh3D.from_file(path)

    assert reread.cell_type_2d == mesh_3d.cell_type_2d
    assert reread.n_layers == mesh_3d.n_layers
    assert reread.n_prisms == mesh_3d.n_prisms
    assert np.allclose(reread.points_xyz, mesh_3d.points_xyz)
    assert np.array_equal(reread.prism_connectivity, mesh_3d.prism_connectivity)
    assert np.array_equal(reread.layer_indices, mesh_3d.layer_indices)
    assert np.array_equal(reread.source_cell_indices, mesh_3d.source_cell_indices)
