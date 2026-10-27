from __future__ import annotations

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from hydromodpy.spatial.field.meshes.gmsh_planar_mesh import (
    GmshPlanarMesh2D,
    load_planar_mesh,
    save_planar_mesh,
)
from hydromodpy.spatial.mesh.io.msh import (
    GmshCellBlock,
    GmshMeshData,
)


def test_triangle_gmsh_planar_mesh_exposes_base_contract():
    mesh = GmshPlanarMesh2D(
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

    assert mesh.kind == "gmsh_2d"
    assert mesh.cell_type == "triangle"
    assert mesh.shape == (4,)
    assert mesh.n_nodes == 4
    assert mesh.n_cells == 2
    assert mesh.bounds == (0.0, 0.0, 1.0, 1.0)

    cells = mesh.cells
    assert len(cells) == 2
    assert cells[0].kind == "triangle"
    assert cells[0].node_indices == (0, 1, 2)
    assert np.allclose(cells[0].centroid, (2.0 / 3.0, 1.0 / 3.0))

    cx, cy = mesh.cell_centroids()
    assert cx.shape == (2,)
    assert cy.shape == (2,)
    assert np.allclose(cx, np.array([2.0 / 3.0, 1.0 / 3.0]))
    assert np.allclose(cy, np.array([1.0 / 3.0, 2.0 / 3.0]))

    values = mesh.to_cell_values(np.array([[10.0], [20.0]], dtype=float))
    assert values.shape == (2,)
    attached = mesh.attach_cell_values(values, label="k")
    assert attached.label == "k"
    assert np.allclose(attached.cell_values, np.array([10.0, 20.0]))


def test_quadrilateral_gmsh_planar_mesh_plot_uses_mesh_bounds():
    mesh = GmshPlanarMesh2D(
        points_xy=np.array(
            [
                [10.0, 30.0],
                [20.0, 30.0],
                [30.0, 30.0],
                [10.0, 50.0],
                [20.0, 50.0],
                [30.0, 50.0],
            ],
            dtype=float,
        ),
        connectivity=np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype=int),
        cell_type="quadrilateral",
    )

    fig, ax = plt.subplots()
    try:
        mappable = mesh.plot_cell_values(ax, np.array([1.0, 2.0], dtype=float), show_mesh=True)
        assert mappable is not None
        assert np.allclose(ax.get_xlim(), (10.0, 30.0))
        assert np.allclose(ax.get_ylim(), (30.0, 50.0))
    finally:
        plt.close(fig)


def test_gmsh_planar_mesh_from_mesh_data_preserves_metadata():
    mesh_data = GmshMeshData(
        points_xy=np.array(
            [
                [0.0, 0.0],
                [2.0, 0.0],
                [2.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        cell_blocks=(
            GmshCellBlock(cell_type="quad", connectivity=np.array([[0, 1, 2, 3]], dtype=int)),
        ),
    )

    mesh = GmshPlanarMesh2D.from_mesh_data(mesh_data)

    assert mesh.cell_type == "quadrilateral"
    assert mesh.n_cells == 1
    assert mesh.as_dict()["cell_type"] == "quadrilateral"
    assert mesh.as_dict()["bounds"] == (0.0, 0.0, 2.0, 1.0)


def test_gmsh_planar_mesh_validates_cell_value_count():
    mesh = GmshPlanarMesh2D(
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

    with pytest.raises(ValueError, match="one value per cell"):
        mesh.to_cell_values(np.array([1.0], dtype=float))


SQUARE = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])


def test_a_planar_mesh_goes_to_meshio_and_comes_back():
    mesh = GmshPlanarMesh2D(
        points_xy=SQUARE, connectivity=[[0, 1, 2], [0, 2, 3]], cell_type="triangles"
    )

    back = GmshPlanarMesh2D.from_meshio(mesh.to_meshio())

    assert back.cell_type == "triangle"
    np.testing.assert_array_equal(back.points_xy, mesh.points_xy)
    np.testing.assert_array_equal(back.connectivity, mesh.connectivity)


def test_a_quadrilateral_hydro_mesh_becomes_a_planar_mesh():
    hydro = GmshPlanarMesh2D(points_xy=SQUARE, connectivity=[[0, 1, 2, 3]], cell_type="quad")

    back = GmshPlanarMesh2D.from_hydro_mesh(hydro.to_hydro_mesh())

    assert back.cell_type == "quadrilateral"
    np.testing.assert_array_equal(back.connectivity, [[0, 1, 2, 3]])


@pytest.mark.parametrize(
    ("points", "connectivity", "reason"),
    [
        (np.zeros((4, 3)), [[0, 1, 2]], "points_xy must have shape"),
        (SQUARE, [[0, 1, 2, 3]], r"triangle connectivity must have shape \(n_cells, 3\)"),
        (SQUARE, [[0, 1, 4]], "outside points_xy"),
    ],
    ids=["xyz points", "quad rows", "node past the points"],
)
def test_a_planar_mesh_checks_its_points_and_its_cells(points, connectivity, reason):
    with pytest.raises(ValueError, match=reason):
        GmshPlanarMesh2D(points_xy=points, connectivity=connectivity, cell_type="triangle")


def test_only_a_planar_hydro_mesh_of_one_fixed_cell_type_becomes_a_planar_mesh():
    from hydromodpy.spatial.mesh.model.cell_types import CellType
    from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

    wedge = HydroMesh(
        vertices=np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float
        ),
        cell_blocks=(CellBlock(CellType.WEDGE, [[0, 1, 2, 3, 4, 5]]),),
    )
    polygons = HydroMesh(
        vertices=SQUARE, cell_blocks=(CellBlock(CellType.POLYGON, (np.array([0, 1, 2, 3]),)),)
    )

    with pytest.raises(TypeError, match="Expected a HydroMesh"):
        GmshPlanarMesh2D.from_hydro_mesh(SQUARE)
    with pytest.raises(ValueError, match="requires a 2D HydroMesh"):
        GmshPlanarMesh2D.from_hydro_mesh(wedge)
    with pytest.raises(NotImplementedError, match="cannot wrap a ragged"):
        GmshPlanarMesh2D.from_hydro_mesh(polygons)


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


def test_a_planar_mesh_saved_with_a_crs_gets_its_projection_file(tmp_path):
    from pyproj import CRS

    from hydromodpy.spatial.mesh.io.msh import read_gmsh_2d_mesh

    path = save_planar_mesh(_build_small_planar_mesh(), tmp_path / "mesh_2d.msh", crs="EPSG:2154")

    assert CRS.from_wkt(read_gmsh_2d_mesh(path).crs_wkt) == CRS.from_epsg(2154)


def test_only_a_planar_mesh_is_saved(tmp_path):
    hydro_mesh = _build_small_planar_mesh().to_hydro_mesh()

    with pytest.raises(TypeError, match="GmshPlanarMesh2D instance"):
        save_planar_mesh(hydro_mesh, tmp_path / "mesh_2d.msh")
