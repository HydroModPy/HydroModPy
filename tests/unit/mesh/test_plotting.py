"""Tests for unified mesh plotting."""

import numpy as np
import pytest

from hydromodpy.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.mesh.plotting import plot_cell_values


@pytest.fixture
def _mpl_backend():
    import matplotlib
    matplotlib.use("Agg")


@pytest.mark.usefixtures("_mpl_backend")
class TestPlotCellValues:
    def test_plot_triangles(self) -> None:
        import matplotlib.pyplot as plt

        verts = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
        conn = np.array([[0, 1, 2], [1, 3, 2]], dtype=int)
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),
        )
        fig, ax = plt.subplots()
        mappable = plot_cell_values(ax, mesh, np.array([1.0, 2.0]))
        assert mappable is not None
        plt.close(fig)

    def test_plot_structured_quads(self) -> None:
        import matplotlib.pyplot as plt

        x, y = np.meshgrid([0, 1, 2], [0, 1])
        verts = np.column_stack((x.ravel(), y.ravel()))
        conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype=int)
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),),
            structured_shape=(1, 2),
        )
        fig, ax = plt.subplots()
        mappable = plot_cell_values(ax, mesh, np.array([1.0, 2.0]))
        assert mappable is not None
        plt.close(fig)

    def test_wrong_size_raises(self) -> None:
        import matplotlib.pyplot as plt

        verts = np.array([[0, 0], [1, 0], [0.5, 1]], dtype=float)
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2]])),),
        )
        fig, ax = plt.subplots()
        with pytest.raises(ValueError, match="1 values"):
            plot_cell_values(ax, mesh, np.array([1.0, 2.0]))
        plt.close(fig)

    def test_3d_mesh_raises(self) -> None:
        import matplotlib.pyplot as plt

        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                          [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float)
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.WEDGE, np.array([[0, 1, 2, 3, 4, 5]])),),
        )
        fig, ax = plt.subplots()
        with pytest.raises(ValueError, match="2D"):
            plot_cell_values(ax, mesh, np.array([1.0]))
        plt.close(fig)
