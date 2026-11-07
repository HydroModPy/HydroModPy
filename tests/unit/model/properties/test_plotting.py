"""One value per cell drawn on a matplotlib axes, for every planar cell type."""

import numpy as np
import pytest

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.model.properties.mesh_cells import cell_mesh_from_edges
from hydromodpy.model.properties.plotting import plot_cell_values
from tests._helpers.cell_meshes import TEST_CRS_WKT, cell_mesh_of
from tests._helpers.mesh_cases import regular_mesh

FOUR_NODES = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
TRIANGLES = np.array([[0, 1, 2], [1, 3, 2]])
TWO_TRIANGLES = HydroMesh(
    vertices=FOUR_NODES, cell_blocks=(CellBlock(CellType.TRIANGLE, TRIANGLES),)
)
TWO_BLOCKS = HydroMesh(
    vertices=FOUR_NODES,
    cell_blocks=tuple(CellBlock(CellType.TRIANGLE, TRIANGLES[[k]]) for k in range(2)),
)
WEDGE = HydroMesh(
    vertices=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], float),
    cell_blocks=(CellBlock(CellType.WEDGE, np.array([[0, 1, 2, 3, 4, 5]])),),
)


@pytest.fixture
def ax():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots()
    yield axes
    plt.close(fig)


@pytest.mark.parametrize(
    ("mesh", "show_mesh"),
    [(TWO_TRIANGLES, False), (TWO_BLOCKS, False), (TWO_TRIANGLES, True)],
    ids=["one-block", "two-blocks", "with-their-edges"],
)
def test_triangles_are_drawn_as_one_triangulation_in_cell_order(ax, mesh, show_mesh) -> None:
    mappable = plot_cell_values(ax, mesh, np.array([1.0, 2.0]), show_mesh=show_mesh)
    # A dropped or reordered cell value would still return a mappable;
    # only comparing the drawn array against the input catches it.
    np.testing.assert_array_equal(np.asarray(mappable.get_array()).ravel(), [1.0, 2.0])
    assert bool(ax.lines) is show_mesh
    assert not show_mesh or ax.get_xlim() == (0.0, 1.5)


@pytest.mark.parametrize("show_mesh", [False, True])
@pytest.mark.parametrize("planar", [False, True], ids=["hydro mesh", "cell mesh"])
def test_plot_structured_quads(ax, show_mesh: bool, planar: bool) -> None:
    mesh = regular_mesh(1, 2) if planar else regular_mesh(1, 2).mesh
    values = np.array([1.0, 2.0])

    mappable = plot_cell_values(ax, mesh, values, show_mesh=show_mesh)

    np.testing.assert_allclose(np.asarray(mappable.get_array()).ravel(), values)
    # One grid line per row edge and per column edge when the mesh is drawn.
    assert len(ax.lines) == ((1 + 1) + (2 + 1) if show_mesh else 0)


@pytest.mark.parametrize(
    ("mesh", "values", "xlim", "ylim"),
    [
        (regular_mesh(1, 1, dx=10.0, dy=20.0, xmin=10.0, ymin=30.0), [1.0], (10.0, 20.0), (30.0, 50.0)),
        (cell_mesh_from_edges([10.0, 20.0, 30.0], [30.0, 50.0], crs_wkt=TEST_CRS_WKT), [1.0, 2.0], (10.0, 30.0),
         (30.0, 50.0)),
    ],
    ids=["regular-grid", "quads-without-a-grid-shape"],
)  # fmt: skip
def test_quads_are_drawn_over_their_own_bounds(ax, mesh, values, xlim, ylim) -> None:
    collection = plot_cell_values(ax, mesh, np.array(values), show_mesh=len(values) > 1)
    np.testing.assert_allclose(np.asarray(collection.get_array()).ravel(), values)
    assert np.allclose(ax.get_xlim(), xlim)
    assert np.allclose(ax.get_ylim(), ylim)


@pytest.mark.parametrize("planar", [False, True], ids=["hydro mesh", "cell mesh"])
def test_plot_ragged_polygons_on_the_color_range_asked(ax, planar: bool) -> None:
    verts = np.array([[1, 0], [1, 1], [0, 1], [-0.3, 0.5], [0, 0], [2, 0], [2, 1]], dtype=float)
    cells = (np.array([0, 1, 2, 3, 4]), np.array([0, 5, 6, 1]))
    mesh = HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.POLYGON, cells),))

    collection = plot_cell_values(
        ax, cell_mesh_of(mesh) if planar else mesh, np.array([1.0, 2.0]), vmin=0.0, vmax=10.0
    )

    np.testing.assert_allclose(np.asarray(collection.get_array()), [1.0, 2.0])
    assert collection.get_clim() == (0.0, 10.0)
    # A padding slot drawn as a corner would add a vertex to the short cell.
    np.testing.assert_array_equal(collection.get_paths()[1].vertices[:4], verts[cells[1]])
    assert [len(path.vertices) for path in collection.get_paths()] == [6, 5]


@pytest.mark.parametrize(
    ("mesh", "values", "match"),
    [(TWO_TRIANGLES, np.ones(3), "2 values"), (WEDGE, np.ones(1), "2D")],
    ids=["wrong-size", "3d-mesh"],
)
def test_values_it_cannot_draw_are_refused(ax, mesh, values, match) -> None:
    with pytest.raises(ValueError, match=match):
        plot_cell_values(ax, mesh, values)
