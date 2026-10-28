"""One value per cell drawn on a matplotlib axes, for every planar cell type."""

import numpy as np
import pytest

from hydromodpy.spatial.field.core.mesh_cells import cell_mesh_from_edges
from hydromodpy.spatial.field.plotting import plot_cell_values
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.cell_meshes import TEST_CRS_WKT, cell_mesh_of
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
    @pytest.mark.parametrize("planar", [False, True], ids=["hydro mesh", "cell mesh"])
    def test_plot_structured_quads(self, show_mesh: bool, planar: bool) -> None:
        import matplotlib.pyplot as plt

        mesh = regular_mesh(1, 2) if planar else regular_mesh(1, 2).mesh
        fig, ax = plt.subplots()
        values = np.array([1.0, 2.0])
        mappable = plot_cell_values(ax, mesh, values, show_mesh=show_mesh)
        np.testing.assert_allclose(np.asarray(mappable.get_array()).ravel(), values)
        # One grid line per row edge and per column edge when the mesh is drawn.
        assert len(ax.lines) == ((1 + 1) + (2 + 1) if show_mesh else 0)
        plt.close(fig)

    def test_a_regular_grid_is_drawn_over_its_own_bounds(self) -> None:
        import matplotlib.pyplot as plt

        mesh = regular_mesh(1, 1, dx=10.0, dy=20.0, xmin=10.0, ymin=30.0)
        fig, ax = plt.subplots()
        plot_cell_values(ax, mesh, np.array([1.0]))
        assert np.allclose(ax.get_xlim(), (10.0, 20.0))
        assert np.allclose(ax.get_ylim(), (30.0, 50.0))
        plt.close(fig)

    def test_quads_without_a_grid_shape_are_drawn_as_polygons(self) -> None:
        import matplotlib.pyplot as plt

        mesh = cell_mesh_from_edges([10.0, 20.0, 30.0], [30.0, 50.0], crs_wkt=TEST_CRS_WKT)
        fig, ax = plt.subplots()
        collection = plot_cell_values(ax, mesh, np.array([1.0, 2.0]), show_mesh=True)
        np.testing.assert_allclose(np.asarray(collection.get_array()), [1.0, 2.0])
        assert np.allclose(ax.get_xlim(), (10.0, 30.0))
        assert np.allclose(ax.get_ylim(), (30.0, 50.0))
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

    @pytest.mark.parametrize("planar", [False, True], ids=["hydro mesh", "cell mesh"])
    def test_plot_ragged_polygons_on_the_colour_range_asked(self, planar: bool) -> None:
        import matplotlib.pyplot as plt

        verts = np.array([[1, 0], [1, 1], [0, 1], [-0.3, 0.5], [0, 0], [2, 0], [2, 1]], dtype=float)
        cells = (np.array([0, 1, 2, 3, 4]), np.array([0, 5, 6, 1]))
        mesh = HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.POLYGON, cells),))
        fig, ax = plt.subplots()
        collection = plot_cell_values(
            ax, cell_mesh_of(mesh) if planar else mesh, np.array([1.0, 2.0]), vmin=0.0, vmax=10.0
        )
        np.testing.assert_allclose(np.asarray(collection.get_array()), [1.0, 2.0])
        assert collection.get_clim() == (0.0, 10.0)
        # A padding slot drawn as a corner would add a vertex to the short cell.
        np.testing.assert_array_equal(collection.get_paths()[1].vertices[:4], verts[cells[1]])
        assert [len(path.vertices) for path in collection.get_paths()] == [6, 5]
        plt.close(fig)

    def test_two_blocks_of_triangles_are_drawn_as_one_triangulation(self) -> None:
        import matplotlib.pyplot as plt

        verts = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
        block = CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2]]))
        other = CellBlock(CellType.TRIANGLE, np.array([[1, 3, 2]]))
        mesh = HydroMesh(vertices=verts, cell_blocks=(block, other))
        fig, ax = plt.subplots()
        mappable = plot_cell_values(ax, mesh, np.array([1.0, 2.0]))
        np.testing.assert_array_equal(mappable.get_array(), [1.0, 2.0])
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
