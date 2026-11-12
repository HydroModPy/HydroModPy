"""The descent D follows the generated network A on the cells A crosses.

A is a raster: the stream pixels, the D8 pointer it was traced on, and its
accumulation. ``prepare_solver`` reads it on the cells once
(``Model.geometry.channel_exits``), and the build pins D on it with its active
columns and its lakes. Each channel cell drains to the next channel cell along
A. Checked on a quad grid and on a brick mesh whose cells meet by faces only.
The projection itself is tested in ``tests/unit/catchment/drainage/test_channel_tree.py``.

``channel_exits_for_build`` says whether a build uses A at all, by the rule of
the run: A off, no folder, rasters missing, or an SFR network that needs it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
from rasterio.transform import from_origin

from hydromodpy.catchment.drainage.channel_tree import ChannelExits, ChannelTree, channel_exits
from hydromodpy.catchment.terrain.port import D8_WBT_OFFSETS
from hydromodpy.mesh.cells.zonal_stats import rasterize_cell_ids
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.model.domain.geometry import ChannelRasters
from hydromodpy.solver.modflow_common.flow_directions import (
    build_solver_mesh_descent,
    channel_exits_for_build,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from, solver_mesh_from_structured_arrays

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


def _exits(tree: ChannelTree, mesh: SolverMesh) -> ChannelExits:
    """A read on the cells of ``mesh``, the way ``prepare_solver`` reads it."""
    labels = rasterize_cell_ids(
        mesh.planar_mesh, transform=tree.transform, out_shape=tree.link.shape
    )
    return channel_exits(tree, labels, n_cells=int(mesh.n_cells))


def _quad(nrow: int, ncol: int, top: np.ndarray, inactive: np.ndarray | None = None):
    """A structured mesh of 10 m cells; mesh row 0 is the NORTH row, like a raster."""
    return solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.asarray(top, dtype=float).reshape(nrow, ncol),
        botm=np.full((1, nrow, ncol), -50.0),
        dx=10.0,
        dy=10.0,
        inactive_mask=inactive,
    )


def _cell(ncol: int, raster_row: int, col: int) -> int:
    """Mesh cell under the raster pixel (one 10 m pixel per cell)."""
    return raster_row * ncol + col


def test_pins_drive_the_receivers_of_d_even_where_the_top_climbs(caplog) -> None:
    nrow = ncol = 8
    path = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]
    tree = _tree((nrow, ncol), path, pixel=10.0, top_y=10.0 * nrow)
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    # T rises to the south-east: A runs uphill on T, a burned channel D must follow.
    top = 50.0 + rows + cols
    cells = [_cell(ncol, r, c) for r, c in path]
    mesh = _quad(nrow, ncol, top)

    with caplog.at_level(logging.INFO):
        descent = build_solver_mesh_descent(
            mesh, lake_cells_by_lake={}, base_level_mask=None, channel_exits=_exits(tree, mesh)
        )

    assert [int(descent.receiver[c]) for c in cells[:-1]] == cells[1:]
    assert descent.pinned[cells[:-1]].all()
    assert np.all(descent.surface[cells[:-1]] > descent.surface[cells[1:]])
    assert "Channel tree A on the mesh: 7 channel cell(s)" in caplog.text


def _brick_mesh(nrow: int, n_bricks: int, top: float) -> SolverMesh:
    """Rows of 2 x 1 bricks, every other row shifted by half a brick.

    Every brick carries the T-junction nodes of its neighbors, so the mesh is
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
    return solver_mesh_from(
        HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),)),
        top=np.full(n, float(top)),
        botm=np.full((1, n), -50.0),
        inactive_mask=np.zeros((1, n), dtype=bool),
    )


def _brick_of(mesh: SolverMesh, x: float, y: float) -> int:
    centroids = mesh.cell_centers()
    for cell, row in enumerate(mesh.planar_mesh.flat_connectivity):
        nodes = row[row >= 0]
        xs = mesh.planar_mesh.vertices[nodes, 0]
        ys = mesh.planar_mesh.vertices[nodes, 1]
        if xs.min() < x < xs.max() and ys.min() < y < ys.max():
            return cell
    raise AssertionError(f"no brick holds ({x}, {y}); centroids {centroids[:3]}")


# -- Whether a build uses A ----------------------------------------------------

_NAMES = ("link.tif", "pointer.tif", "accumulation.tif")


def _rasters(folder: Path, *, enabled: bool = True) -> ChannelRasters:
    link, pointer, accumulation = (str(folder / name) for name in _NAMES)
    return ChannelRasters(enabled=enabled, link=link, pointer=pointer, accumulation=accumulation)


def _write_files(folder: Path) -> None:
    for name in _NAMES:
        (folder / name).write_bytes(b"")


def _some_exits() -> ChannelExits:
    return ChannelExits(np.ones(2, bool), np.array([1, -1]), np.array([True, False]))


@pytest.mark.parametrize("required", [False, True])
def test_a_build_uses_the_exits_of_the_model_with_or_without_the_sfr_need(
    tmp_path: Path, required: bool
) -> None:
    _write_files(tmp_path)
    exits = _some_exits()

    assert channel_exits_for_build(_rasters(tmp_path), exits, required=required) is exits


def test_a_network_that_the_sfr_needs_without_a_folder_pins_nothing_and_says_why(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO"):
        assert channel_exits_for_build(None, None, required=True) is None

    assert "No corrected-flow folder" in caplog.text


def test_the_clipped_rasters_alone_are_never_the_network(caplog) -> None:
    rasters = ChannelRasters(True, None, None, None, clipped=("clipped.tif",))

    with caplog.at_level("INFO"):
        assert channel_exits_for_build(rasters, None, required=True) is None
    assert "No corrected-flow folder" in caplog.text


def test_missing_rasters_are_an_error_only_when_the_sfr_lies_on_the_network(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rasters = _rasters(tmp_path)

    with caplog.at_level("INFO"):
        assert channel_exits_for_build(rasters, None) is None
    assert f"No generated river network A in {tmp_path}" in caplog.text
    with pytest.raises(FileNotFoundError, match="rasters are missing"):
        channel_exits_for_build(rasters, None, required=True)


@pytest.mark.parametrize("required", [False, True])
def test_a_model_that_did_not_read_a_it_serves_is_refused(tmp_path: Path, required: bool) -> None:
    _write_files(tmp_path)

    with pytest.raises(ValueError, match="channel_exits is None"):
        channel_exits_for_build(_rasters(tmp_path), None, required=required)
