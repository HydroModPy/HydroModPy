"""The descent D follows the generated network A on the cells A crosses.

A is a raster: the stream pixels, the D8 pointer it was traced on, and its
accumulation. ``prepare_solver`` reads it on the cells once
(``Model.geometry.channel_exits``), and the build pins D on it. Each channel cell
drains to the next channel cell along A, even where the cell top climbs.
``channel_exits_for_build`` says whether a build uses A at all: A off, no folder,
rasters missing, or an SFR network that needs it. The projection itself is tested
in ``tests/unit/catchment/drainage/test_channel_tree.py``. Cell sizes are 10 m.
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
from hydromodpy.model.domain.geometry import ChannelRasters
from hydromodpy.solver.modflow_common.flow_directions import (
    build_solver_mesh_descent,
    channel_exits_for_build,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

CODE_OF_STEP = {step: code for code, step in D8_WBT_OFFSETS.items()}
RASTER_NAMES = ("link.tif", "pointer.tif", "accumulation.tif")


def channel_tree(
    shape: tuple[int, int], path: list[tuple[int, int]], *, pixel: float, top_y: float
):
    """A raster tree along ``path`` (raster rows from the north), accumulation growing down it."""
    link = np.zeros(shape, dtype=bool)
    pointer = np.zeros(shape, dtype=np.int64)
    accumulation = np.ones(shape, dtype=float)
    for index, (row, col) in enumerate(path):
        link[row, col] = True
        accumulation[row, col] = 10.0 + index
        if index + 1 < len(path):
            nxt = path[index + 1]
            pointer[row, col] = CODE_OF_STEP[(nxt[0] - row, nxt[1] - col)]
    return ChannelTree(
        link=link,
        pointer=pointer,
        accumulation=accumulation,
        transform=from_origin(0.0, top_y, pixel, pixel),
    )


def exits_on(tree: ChannelTree, mesh: SolverMesh) -> ChannelExits:
    """A read on the cells of ``mesh``, the way ``prepare_solver`` reads it."""
    labels = rasterize_cell_ids(
        mesh.planar_mesh, transform=tree.transform, out_shape=tree.link.shape
    )
    return channel_exits(tree, labels, n_cells=int(mesh.n_cells))


def quad_mesh_of(nrow: int, ncol: int, top: np.ndarray) -> SolverMesh:
    """A structured mesh of 10 m cells. Mesh row 0 is the north row, like a raster."""
    return solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.asarray(top, dtype=float).reshape(nrow, ncol),
        botm=np.full((1, nrow, ncol), -50.0),
        dx=10.0,
        dy=10.0,
        inactive_mask=None,
    )


def rasters_in(folder: Path, *, files: bool = True) -> ChannelRasters:
    link, pointer, accumulation = (str(folder / name) for name in RASTER_NAMES)
    if files:
        for name in RASTER_NAMES:
            (folder / name).write_bytes(b"")
    return ChannelRasters(enabled=True, link=link, pointer=pointer, accumulation=accumulation)


def some_exits() -> ChannelExits:
    return ChannelExits(np.ones(2, bool), np.array([1, -1]), np.array([True, False]))


def test_pins_drive_the_receivers_even_where_the_top_climbs(caplog) -> None:
    nrow = ncol = 8
    path = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]
    tree = channel_tree((nrow, ncol), path, pixel=10.0, top_y=10.0 * nrow)
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    # T rises to the south-east: A runs uphill on T, a burned channel D must follow.
    top = 50.0 + rows + cols
    cells = [row * ncol + col for row, col in path]
    mesh = quad_mesh_of(nrow, ncol, top)

    with caplog.at_level(logging.INFO):
        descent = build_solver_mesh_descent(
            mesh, lake_cells_by_lake={}, base_level_mask=None, channel_exits=exits_on(tree, mesh)
        )

    assert [int(descent.receiver[c]) for c in cells[:-1]] == cells[1:]
    assert descent.pinned[cells[:-1]].all()
    assert np.all(descent.surface[cells[:-1]] > descent.surface[cells[1:]])
    assert "Channel tree A on the mesh: 7 channel cell(s)" in caplog.text


@pytest.mark.parametrize("required", [False, True], ids=["sfr not needed", "sfr needed"])
def test_build_uses_the_exits_of_the_model(tmp_path: Path, required: bool) -> None:
    exits = some_exits()

    assert channel_exits_for_build(rasters_in(tmp_path), exits, required=required) is exits


NO_FOLDER = [
    pytest.param(None, id="no rasters"),
    pytest.param(
        ChannelRasters(True, None, None, None, clipped=("clipped.tif",)), id="clipped only"
    ),
]


@pytest.mark.parametrize("rasters", NO_FOLDER)
def test_network_needed_without_a_folder_pins_nothing(rasters, caplog) -> None:
    with caplog.at_level("INFO"):
        assert channel_exits_for_build(rasters, None, required=True) is None

    assert "No corrected-flow folder" in caplog.text


def test_missing_rasters_are_an_error_only_when_the_sfr_needs_them(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rasters = rasters_in(tmp_path, files=False)

    with caplog.at_level("INFO"):
        assert channel_exits_for_build(rasters, None) is None
    assert f"No generated river network A in {tmp_path}" in caplog.text
    with pytest.raises(FileNotFoundError, match="rasters are missing"):
        channel_exits_for_build(rasters, None, required=True)


@pytest.mark.parametrize("required", [False, True], ids=["sfr not needed", "sfr needed"])
def test_refuses_a_model_that_did_not_read_a(tmp_path: Path, required: bool) -> None:
    with pytest.raises(ValueError, match="channel_exits is None"):
        channel_exits_for_build(rasters_in(tmp_path), None, required=required)
