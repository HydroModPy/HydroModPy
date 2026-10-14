from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh.gmsh_grid import (
    GmshPlanarMesh2D,
    load_hydro_mesh_vtu,
    load_planar_as_hydro_mesh,
    load_planar_mesh,
    save_hydro_mesh_vtu,
    save_planar_mesh,
)


def _build_small_planar_mesh() -> GmshPlanarMesh2D:
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


def test_a_planar_mesh_written_as_msh_reads_back(tmp_path):
    pytest.importorskip("meshio")
    planar_mesh = _build_small_planar_mesh()

    path = save_planar_mesh(planar_mesh, tmp_path / "mesh_2d.msh")
    reread = load_planar_mesh(path)

    assert reread.n_cells == planar_mesh.n_cells
    assert np.allclose(reread.points_xy, planar_mesh.points_xy)
    assert np.array_equal(reread.connectivity, planar_mesh.connectivity)


def test_a_planar_mesh_loads_as_a_hydro_mesh(tmp_path):
    pytest.importorskip("meshio")
    planar_mesh = _build_small_planar_mesh()
    path = save_planar_mesh(planar_mesh, tmp_path / "mesh_2d.msh")

    hydro_mesh = load_planar_as_hydro_mesh(path)

    assert hydro_mesh.n_cells == planar_mesh.n_cells
    assert np.allclose(hydro_mesh.vertices[:, :2], planar_mesh.points_xy)


def test_a_hydro_mesh_written_as_vtu_reads_back(tmp_path):
    pytest.importorskip("meshio")
    hydro_mesh = _build_small_planar_mesh().to_hydro_mesh()

    path = save_hydro_mesh_vtu(hydro_mesh, tmp_path / "mesh.vtu")
    reread = load_hydro_mesh_vtu(path)

    assert reread.n_cells == hydro_mesh.n_cells
    assert np.allclose(reread.vertices[:, :2], hydro_mesh.vertices[:, :2])
