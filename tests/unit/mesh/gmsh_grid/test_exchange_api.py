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
    planar_mesh = _build_small_planar_mesh()

    path = save_planar_mesh(planar_mesh, tmp_path / "mesh_2d.msh")
    reread = load_planar_mesh(path)

    assert reread.n_cells == planar_mesh.n_cells
    assert np.allclose(reread.points_xy, planar_mesh.points_xy)
    assert np.array_equal(reread.connectivity, planar_mesh.connectivity)


def test_a_planar_mesh_loads_as_a_hydro_mesh(tmp_path):
    planar_mesh = _build_small_planar_mesh()
    path = save_planar_mesh(planar_mesh, tmp_path / "mesh_2d.msh")

    hydro_mesh = load_planar_as_hydro_mesh(path)

    assert hydro_mesh.n_cells == planar_mesh.n_cells
    assert np.allclose(hydro_mesh.vertices[:, :2], planar_mesh.points_xy)


def test_a_hydro_mesh_written_as_vtu_reads_back(tmp_path):
    hydro_mesh = _build_small_planar_mesh().to_hydro_mesh()

    path = save_hydro_mesh_vtu(hydro_mesh, tmp_path / "mesh.vtu")
    reread = load_hydro_mesh_vtu(path)

    assert reread.n_cells == hydro_mesh.n_cells
    assert np.allclose(reread.vertices[:, :2], hydro_mesh.vertices[:, :2])


def test_a_planar_mesh_saved_with_a_crs_gets_its_projection_file(tmp_path):
    from pyproj import CRS

    from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import read_gmsh_2d_mesh

    path = save_planar_mesh(_build_small_planar_mesh(), tmp_path / "mesh_2d.msh", crs="EPSG:2154")

    assert CRS.from_wkt(read_gmsh_2d_mesh(path).crs_wkt) == CRS.from_epsg(2154)


def test_only_a_planar_mesh_is_saved(tmp_path):
    hydro_mesh = _build_small_planar_mesh().to_hydro_mesh()

    with pytest.raises(TypeError, match="GmshPlanarMesh2D instance"):
        save_planar_mesh(hydro_mesh, tmp_path / "mesh_2d.msh")


def test_the_package_names_what_it_does_not_export():
    import hydromodpy.spatial.mesh.gmsh_grid as gmsh_grid

    with pytest.raises(AttributeError, match="has no attribute 'write_bundle'"):
        _ = gmsh_grid.write_bundle
