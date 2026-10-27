"""One value per cell drawn on a matplotlib axes, for every planar cell type."""

import numpy as np
import pytest

from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.plotting import plot_cell_values
from tests._helpers.mesh_cases import regular_mesh


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
        values = np.array([1.0, 2.0])
        mappable = plot_cell_values(ax, mesh, values)
        # A dropped or reordered cell value would still return a mappable;
        # only comparing the drawn array against the input catches it.
        np.testing.assert_allclose(np.asarray(mappable.get_array()).ravel(), values)
        plt.close(fig)

    @pytest.mark.parametrize("show_mesh", [False, True])
    def test_plot_structured_quads(self, show_mesh: bool) -> None:
        import matplotlib.pyplot as plt

        mesh = regular_mesh(1, 2).mesh
        fig, ax = plt.subplots()
        values = np.array([1.0, 2.0])
        mappable = plot_cell_values(ax, mesh, values, show_mesh=show_mesh)
        np.testing.assert_allclose(np.asarray(mappable.get_array()).ravel(), values)
        # One grid line per row edge and per column edge when the mesh is drawn.
        assert len(ax.lines) == ((1 + 1) + (2 + 1) if show_mesh else 0)
        plt.close(fig)

    def test_plot_triangles_with_their_edges(self) -> None:
        import matplotlib.pyplot as plt

        verts = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [1, 3, 2]])),),
        )
        fig, ax = plt.subplots()
        plot_cell_values(ax, mesh, np.array([1.0, 2.0]), show_mesh=True)
        assert ax.lines
        assert ax.get_xlim() == (0.0, 1.5)
        plt.close(fig)

    def test_plot_ragged_polygons_on_the_colour_range_asked(self) -> None:
        import matplotlib.pyplot as plt

        verts = np.array([[1, 0], [1, 1], [0, 1], [-0.3, 0.5], [0, 0], [2, 0], [2, 1]], dtype=float)
        cells = (np.array([0, 1, 2, 3, 4]), np.array([0, 5, 6, 1]))
        mesh = HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.POLYGON, cells),))
        fig, ax = plt.subplots()
        collection = plot_cell_values(ax, mesh, np.array([1.0, 2.0]), vmin=0.0, vmax=10.0)
        np.testing.assert_allclose(np.asarray(collection.get_array()), [1.0, 2.0])
        assert collection.get_clim() == (0.0, 10.0)
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

        verts = np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float
        )
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.WEDGE, np.array([[0, 1, 2, 3, 4, 5]])),),
        )
        fig, ax = plt.subplots()
        with pytest.raises(ValueError, match="2D"):
            plot_cell_values(ax, mesh, np.array([1.0]))
        plt.close(fig)
