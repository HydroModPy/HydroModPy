from __future__ import annotations

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from hydromodpy.solver.utils.mesh.gmsh_grid import GmshPlanarMesh2D
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader import GmshCellBlock, GmshMeshData


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
