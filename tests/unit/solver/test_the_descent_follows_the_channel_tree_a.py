"""The descent D follows the generated network A on the cells A crosses.

A is a raster: the stream pixels, the D8 pointer it was traced on, and its
accumulation. Each mesh cell holding a pixel of A is a channel cell pinned to
the next channel cell along A; a lake cell is never one, and a cell where A
leaves through a lake or off the raster is an outlet of A. Checked on a quad
grid and on a brick mesh whose cells meet by faces only.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
from rasterio.transform import from_origin

from hydromodpy.solver.modflow6.support.mesh_descent import (
    ChannelTree,
    build_solver_mesh_descent,
    project_channel_tree,
    read_channel_tree,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS

_CODE_OF_STEP = {step: code for code, step in D8_WBT_OFFSETS.items()}


def _tree(shape: tuple[int, int], path: list[tuple[int, int]], *, pixel: float, top_y: float):
    """A raster tree along ``path`` (raster rows from the north), accumulation growing down it."""
    link = np.zeros(shape, dtype=bool)
    pointer = np.zeros(shape, dtype=np.int64)
    accumulation = np.ones(shape, dtype=float)
    for index, (row, col) in enumerate(path):
        link[row, col] = True
        accumulation[row, col] = 10.0 + index
        if index + 1 < len(path):
            nxt = path[index + 1]
            pointer[row, col] = _CODE_OF_STEP[(nxt[0] - row, nxt[1] - col)]
    return ChannelTree(
        link=link,
        pointer=pointer,
        accumulation=accumulation,
        transform=from_origin(0.0, top_y, pixel, pixel),
    )


def _quad(nrow: int, ncol: int, top: np.ndarray, inactive: np.ndarray | None = None):
    """A structured mesh of 10 m cells; mesh row 0 is the SOUTH row."""
    return SolverMesh.from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.asarray(top, dtype=float).reshape(nrow, ncol),
        botm=np.full((1, nrow, ncol), -50.0),
        dx=10.0,
        dy=10.0,
        inactive_mask=inactive,
    )


def _cell(nrow: int, ncol: int, raster_row: int, col: int) -> int:
    """Mesh cell under the raster pixel (one 10 m pixel per cell)."""
    return (nrow - 1 - raster_row) * ncol + col


def test_a_staircase_of_a_pins_each_cell_to_the_next_one_on_a() -> None:
    nrow = ncol = 8
    path = [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4), (5, 5), (6, 6)]
    tree = _tree((nrow, ncol), path, pixel=10.0, top_y=10.0 * nrow)
    mesh = _quad(nrow, ncol, np.full(nrow * ncol, 50.0))
    cells = [_cell(nrow, ncol, r, c) for r, c in path]
    n = nrow * ncol

    pinned, channel = project_channel_tree(
        tree, mesh.planar_mesh, routable=np.ones(n, dtype=bool), lake_of=np.full(n, -1)
    )

    assert np.flatnonzero(channel).tolist() == sorted(cells)
    assert [int(pinned[c]) for c in cells] == cells[1:] + [-1]
    assert np.all(pinned[~channel] == -1)


def test_pins_drive_the_receivers_of_d_even_where_the_top_climbs(caplog) -> None:
    nrow = ncol = 8
    path = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]
    tree = _tree((nrow, ncol), path, pixel=10.0, top_y=10.0 * nrow)
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    # T rises to the south-east: A runs uphill on T, a burned channel D must follow.
    top = 50.0 + (nrow - 1 - rows) + cols
    cells = [_cell(nrow, ncol, r, c) for r, c in path]
    mesh = _quad(nrow, ncol, top)

    with caplog.at_level(logging.INFO):
        descent = build_solver_mesh_descent(
            mesh, lake_cells_by_lake={}, base_level_mask=None, channel_tree=tree
        )

    assert [int(descent.receiver[c]) for c in cells[:-1]] == cells[1:]
    assert descent.pinned[cells[:-1]].all()
    assert np.all(descent.surface[cells[:-1]] > descent.surface[cells[1:]])
    assert "Channel tree A on the mesh: 7 channel cell(s)" in caplog.text


def test_a_flat_beside_a_drains_into_a_not_along_it() -> None:
    # A valley floor three cells wide, flat at 10 m between walls at 20 m, narrows
    # to one cell and spills through one rim cell at 9 m to the south. A runs
    # down its middle column. The plain flood sends the side cells down their own
    # column, beside A; the pinned flood sends them into A.
    nrow, ncol = 12, 7
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    top = np.full(nrow * ncol, 20.0)
    valley = (rows >= 2) & (rows <= nrow - 2) & (cols >= 2) & (cols <= 4)
    top[valley | ((rows == 1) & (cols == 3))] = 10.0
    top[(rows == 0) & (cols == 3)] = 9.0
    path = [(r, 3) for r in range(1, nrow)]  # raster rows from the north, down to the spill
    tree = _tree((nrow, ncol), path, pixel=10.0, top_y=10.0 * nrow)
    mesh = _quad(nrow, ncol, top)
    side = np.flatnonzero(valley & (cols != 3))
    a_cells = np.flatnonzero(cols == 3)

    plain = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    pinned = build_solver_mesh_descent(
        mesh, lake_cells_by_lake={}, base_level_mask=None, channel_tree=tree
    )

    assert not np.isin(plain.receiver[side], a_cells).all()
    assert pinned.channel[pinned.receiver[side]].all(), "a flat cell beside A runs along it"


def test_a_leaves_through_a_lake_so_the_cell_above_it_is_an_outlet_of_a() -> None:
    nrow, ncol = 8, 5
    path = [(r, 2) for r in range(1, 7)]
    tree = _tree((nrow, ncol), path, pixel=10.0, top_y=10.0 * nrow)
    n = nrow * ncol
    lake_cell = _cell(nrow, ncol, 3, 2)
    lake_of = np.full(n, -1)
    lake_of[lake_cell] = 0
    above, below = _cell(nrow, ncol, 2, 2), _cell(nrow, ncol, 4, 2)

    pinned, channel = project_channel_tree(
        tree,
        _quad(nrow, ncol, np.zeros(n)).planar_mesh,
        routable=np.ones(n, dtype=bool),
        lake_of=lake_of,
    )

    assert not channel[lake_cell]
    assert pinned[lake_cell] == -1
    assert lake_cell not in pinned.tolist()
    assert pinned[above] == -1
    assert channel[below] and pinned[below] == _cell(nrow, ncol, 5, 2)


def test_a_cell_off_the_graph_is_neither_a_channel_nor_a_pin() -> None:
    nrow, ncol = 6, 3
    path = [(r, 1) for r in range(1, 5)]
    tree = _tree((nrow, ncol), path, pixel=10.0, top_y=10.0 * nrow)
    n = nrow * ncol
    routable = np.ones(n, dtype=bool)
    off = _cell(nrow, ncol, 3, 1)
    routable[off] = False

    pinned, channel = project_channel_tree(
        tree,
        _quad(nrow, ncol, np.zeros(n)).planar_mesh,
        routable=routable,
        lake_of=np.full(n, -1),
    )

    assert not channel[off]
    assert pinned[_cell(nrow, ncol, 2, 1)] == -1
    assert off not in pinned.tolist()


def test_a_pointer_that_closes_a_loop_is_refused() -> None:
    nrow = ncol = 4
    tree = _tree((nrow, ncol), [(1, 1), (1, 2), (2, 2), (2, 1)], pixel=10.0, top_y=40.0)
    tree.pointer[2, 1] = _CODE_OF_STEP[(-1, 0)]  # back to (1, 1)
    n = nrow * ncol

    with pytest.raises(ValueError, match="closes a loop"):
        project_channel_tree(
            tree,
            _quad(nrow, ncol, np.zeros(n)).planar_mesh,
            routable=np.ones(n, dtype=bool),
            lake_of=np.full(n, -1),
        )


def _brick_mesh(nrow: int, n_bricks: int, top: float) -> SolverMesh:
    """Rows of 2 x 1 bricks, every other row shifted by half a brick.

    Every brick carries the T-junction nodes of its neighbours, so the mesh is
    not all-quad and D descends by shared faces, like a Voronoi mesh.
    """
    width = 2 * n_bricks
    vertices = np.array([[float(x), float(y)] for y in range(nrow + 1) for x in range(width + 1)])

    def node(x: int, y: int) -> int:
        return y * (width + 1) + x

    cells: list[list[int]] = []
    for row in range(nrow):
        edges = list(range(0, width + 1, 2)) if row % 2 == 0 else [0, *range(1, width, 2), width]
        for x0, x1 in zip(edges[:-1], edges[1:], strict=True):
            bottom = [node(x, row) for x in range(x0, x1 + 1)]
            top_edge = [node(x, row + 1) for x in range(x1, x0 - 1, -1)]
            cells.append(bottom + top_edge)
    n = len(cells)
    return SolverMesh(
        planar_mesh=HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),)),
        top=np.full(n, float(top)),
        botm=np.full((1, n), -50.0),
        inactive_mask=np.zeros((1, n), dtype=bool),
    )


def _brick_of(mesh: SolverMesh, x: float, y: float) -> int:
    centroids = mesh.cell_centroids()
    for cell, nodes in enumerate(mesh.planar_mesh.flat_connectivity):
        xs = mesh.planar_mesh.vertices[np.asarray(nodes), 0]
        ys = mesh.planar_mesh.vertices[np.asarray(nodes), 1]
        if xs.min() < x < xs.max() and ys.min() < y < ys.max():
            return cell
    raise AssertionError(f"no brick holds ({x}, {y}); centroids {centroids[:3]}")


def test_on_a_brick_mesh_a_runs_down_pinned_bricks_and_d_follows_it() -> None:
    nrow, n_bricks = 8, 4
    mesh = _brick_mesh(nrow, n_bricks, 30.0)
    n = int(mesh.n_cells)
    # One-metre pixels; A runs south down raster column 3, from row 1 to row 6.
    path = [(r, 3) for r in range(1, 7)]
    tree = _tree((nrow, 2 * n_bricks), path, pixel=1.0, top_y=float(nrow))
    bricks = [_brick_of(mesh, 3.5, nrow - r - 0.5) for r, _ in path]

    pinned, channel = project_channel_tree(
        tree, mesh.planar_mesh, routable=np.ones(n, dtype=bool), lake_of=np.full(n, -1)
    )
    descent = build_solver_mesh_descent(
        mesh, lake_cells_by_lake={}, base_level_mask=None, channel_tree=tree
    )

    assert np.flatnonzero(channel).tolist() == sorted(bricks)
    assert [int(pinned[b]) for b in bricks] == bricks[1:] + [-1]
    assert not descent.diagonal_neighbors
    # A seed is never pinned; every other brick of A follows its pin.
    followed = [b for b in bricks[:-1] if not descent.base_level[b]]
    assert followed
    assert all(int(descent.receiver[b]) == int(pinned[b]) for b in followed)


def test_the_tree_is_read_on_a_window_around_the_mesh(tmp_path) -> None:
    import rasterio

    shape = (20, 30)
    transform = from_origin(-100.0, 200.0, 10.0, 10.0)
    link = np.zeros(shape, dtype=np.int32)
    link[5, 12] = 7
    profile = {
        "driver": "GTiff",
        "height": shape[0],
        "width": shape[1],
        "count": 1,
        "transform": transform,
    }
    paths = {}
    for name, data in (
        ("link", link),
        ("pointer", np.full(shape, 2, dtype=np.int32)),
        ("acc", np.arange(np.prod(shape), dtype=np.float32).reshape(shape)),
    ):
        paths[name] = tmp_path / f"{name}.tif"
        with rasterio.open(paths[name], "w", dtype=data.dtype, **profile) as dst:
            dst.write(data, 1)

    tree = read_channel_tree(
        link_tif=str(paths["link"]),
        pointer_tif=str(paths["pointer"]),
        accumulation_tif=str(paths["acc"]),
        bounds=(0.0, 100.0, 50.0, 150.0),
    )

    # Mesh bounds cover columns 10..14 and rows 5..9, plus one pixel of margin.
    assert tree.link.shape == (7, 7)
    assert tree.transform.c == pytest.approx(-10.0) and tree.transform.f == pytest.approx(160.0)
    assert np.argwhere(tree.link).tolist() == [[1, 3]]

    with rasterio.open(
        tmp_path / "shifted.tif", "w", dtype="int32", **{**profile, "width": shape[1] + 1}
    ) as dst:
        dst.write(np.zeros((shape[0], shape[1] + 1), dtype=np.int32), 1)
    with pytest.raises(ValueError, match="misaligned"):
        read_channel_tree(
            link_tif=str(paths["link"]),
            pointer_tif=str(tmp_path / "shifted.tif"),
            accumulation_tif=str(paths["acc"]),
            bounds=(0.0, 100.0, 50.0, 150.0),
        )
