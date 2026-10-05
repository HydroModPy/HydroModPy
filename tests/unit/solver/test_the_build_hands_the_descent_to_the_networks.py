"""The MF6 build builds D only for a network that walks it, and hands it on.

D is built when a network sets ``rectify_on_mesh`` or ``route_drainage``, with
the CHD cells as outlets. ``resolve_sfr_networks`` traces a rectified channel on
it and prunes its stubs on shared faces. The drainage basin closes on the
snapped outlet, falls back on the watershed polygon, and warns on a large gap.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.transform import from_origin

from hydromodpy.physics.flow.sinks_sources.sfr import FlowReachConfig, FlowReachNetworkConfig
from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow6.builders.sfr import resolve_sfr_networks
from hydromodpy.solver.modflow6.support.mesh_descent import (
    ChannelTree,
    build_solver_mesh_descent,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS

_CODE_OF_STEP = {step: code for code, step in D8_WBT_OFFSETS.items()}


def _mesh(nrow: int, ncol: int, top: np.ndarray) -> SolverMesh:
    """10 m cells; mesh row 0 is the SOUTH row, cell id ``row * ncol + col``."""
    return SolverMesh.from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.asarray(top, dtype=float).reshape(nrow, ncol),
        botm=np.full((1, nrow, ncol), -50.0),
        dx=10.0,
        dy=10.0,
    )


def _model(sfr: dict, **extra) -> SimpleNamespace:
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=["sfr"], sinks_sources={"sfr": sfr}), **extra
    )


def _no_chd(n: int) -> dict:
    return {
        "_ocean_support_mask": np.zeros(n, dtype=bool),
        "_stream_support_mask": np.zeros(n, dtype=bool),
        "geographic": None,
    }


def test_a_network_that_walks_no_descent_builds_none() -> None:
    mesh = _mesh(5, 5, np.full(25, 10.0))
    model = _model({"net0": {"route_drainage": False}}, **_no_chd(25))

    assert build._sfr_descent(model, mesh, {}) is None


def test_route_drainage_builds_d_with_the_chd_cells_as_outlets() -> None:
    n = 7
    rows, cols = np.divmod(np.arange(n * n), n)
    mesh = _mesh(n, n, 10.0 + rows + cols)
    ocean = np.zeros(n * n, dtype=bool)
    river = np.zeros(n * n, dtype=bool)
    ocean[3 * n + 3] = True
    river[5 * n + 2] = True
    model = _model(
        {"net0": {"route_drainage": True}},
        _ocean_support_mask=ocean,
        _stream_support_mask=river,
        geographic=None,
    )

    descent = build._sfr_descent(model, mesh, {})

    assert descent is not None
    for cell in (3 * n + 3, 5 * n + 2):
        assert descent.base_level[cell]
        assert descent.receiver[cell] == -1
    assert not descent.pinned.any()


def _staircase_tree(nrow: int, ncol: int, path: list[tuple[int, int]]) -> ChannelTree:
    link = np.zeros((nrow, ncol), dtype=bool)
    pointer = np.zeros((nrow, ncol), dtype=np.int64)
    accumulation = np.ones((nrow, ncol))
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
        transform=from_origin(0.0, 10.0 * nrow, 10.0, 10.0),
    )


def _rectify_payload(row: int, col: int) -> FlowReachNetworkConfig:
    reach = FlowReachConfig(
        cell={"kind": "cell", "cell": [0, row, col]},
        length="10 m",
        width="2 m",
        slope=1e-3,
        top=40.0,
        upstream=[],
        downstream=[],
    )
    return FlowReachNetworkConfig(reaches=[reach], rectify_on_mesh=True)


def test_rectify_on_mesh_without_a_descent_is_refused() -> None:
    mesh = _mesh(5, 5, np.full(25, 10.0))
    model = _model({"net0": _rectify_payload(2, 2)})

    with pytest.raises(ValueError, match=r"net0\.rectify_on_mesh"):
        resolve_sfr_networks(model, solver_mesh=mesh)


def test_rectify_on_mesh_traces_d_and_keeps_a_lone_staircase_whole() -> None:
    # A staircase of 11 cells on an 8 x 8 grid, pinned in D. On D's D8 adjacency
    # the head of the staircase would read as a stub beside its own channel.
    nrow = ncol = 8
    path = [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4), (4, 5), (5, 5), (5, 6), (6, 6)]
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    raster_rows = nrow - 1 - rows
    mesh = _mesh(nrow, ncol, 50.0 - raster_rows - cols)
    descent = build_solver_mesh_descent(
        mesh,
        lake_cells_by_lake={},
        base_level_mask=None,
        channel_tree=_staircase_tree(nrow, ncol, path),
    )
    staircase = [(nrow - 1 - r) * ncol + c for r, c in path]
    head_row, head_col = divmod(staircase[0], ncol)
    model = _model({"net0": _rectify_payload(head_row, head_col)})

    networks = resolve_sfr_networks(model, solver_mesh=mesh, descent=descent)

    reach_cells = {int(reach.cellid[1]) for reach in networks["net0"].reaches}
    assert set(staircase) <= reach_cells


def _two_valleys(nrow: int = 10, ncol: int = 10) -> SolverMesh:
    """Two valleys running south, centred on columns 2 and 7."""
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    centre = np.where(cols < 5, 2, 7)
    return _mesh(nrow, ncol, 100.0 + 0.5 * rows + np.abs(cols - centre))


def _xy(row: int, col: int) -> tuple[float, float]:
    return (10.0 * col + 5.0, 10.0 * row + 5.0)


def test_the_drainage_basin_closes_on_the_snapped_outlet(monkeypatch) -> None:
    mesh = _two_valleys()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    monkeypatch.setattr(build, "_watershed_polygon_mask", lambda model, centroids: None)
    snapped, declared = _xy(0, 2), _xy(0, 7)
    model = SimpleNamespace(
        geographic=SimpleNamespace(
            x_outlet=declared[0],
            y_outlet=declared[1],
            x_outlet_snapped=snapped[0],
            y_outlet_snapped=snapped[1],
        )
    )

    basin = build._drainage_basin(model, descent, mesh)

    assert basin[5 * 10 + 2]
    assert not basin[5 * 10 + 7]


def test_without_a_snapped_outlet_the_declared_one_closes_the_basin(monkeypatch) -> None:
    mesh = _two_valleys()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    monkeypatch.setattr(build, "_watershed_polygon_mask", lambda model, centroids: None)
    declared = _xy(0, 7)
    model = SimpleNamespace(geographic=SimpleNamespace(x_outlet=declared[0], y_outlet=declared[1]))

    basin = build._drainage_basin(model, descent, mesh)

    assert basin[5 * 10 + 7]
    assert not basin[5 * 10 + 2]


def test_without_an_outlet_the_basin_closes_inside_the_polygon(monkeypatch, caplog) -> None:
    mesh = _two_valleys()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    east = mesh.cell_centroids()[:, 0] > 50.0
    monkeypatch.setattr(build, "_watershed_polygon_mask", lambda model, centroids: east)
    model = SimpleNamespace(geographic=None)

    with caplog.at_level(logging.INFO):
        basin = build._drainage_basin(model, descent, mesh)

    assert basin[5 * 10 + 7]
    assert not basin[5 * 10 + 2]
    assert "Drainage basin of D" in caplog.text


def test_a_basin_far_from_the_polygon_is_a_warning(monkeypatch, caplog) -> None:
    mesh = _two_valleys()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    east = mesh.cell_centroids()[:, 0] > 50.0
    monkeypatch.setattr(build, "_watershed_polygon_mask", lambda model, centroids: east)
    snapped = _xy(0, 2)
    model = SimpleNamespace(
        geographic=SimpleNamespace(x_outlet_snapped=snapped[0], y_outlet_snapped=snapped[1])
    )

    with caplog.at_level(logging.INFO):
        build._drainage_basin(model, descent, mesh)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Drainage basin of D" in r.getMessage() for r in warnings)


def _write_network_rasters(folder, shape: tuple[int, int]) -> None:
    import rasterio

    profile = {
        "driver": "GTiff",
        "height": shape[0],
        "width": shape[1],
        "count": 1,
        "transform": from_origin(0.0, 10.0 * shape[0], 10.0, 10.0),
    }
    link = np.zeros(shape, dtype=np.int32)
    link[2, 1:4] = 1
    for name, data in (
        ("dem_stream_link_id_full.tif", link),
        ("dem_direc.tif", np.full(shape, _CODE_OF_STEP[(0, 1)], dtype=np.int32)),
        ("dem_acc_cells.tif", np.tile(np.arange(shape[1], dtype=np.float32), (shape[0], 1))),
    ):
        with rasterio.open(folder / name, "w", dtype=data.dtype, **profile) as dst:
            dst.write(data, 1)


def test_a_is_read_from_the_corrected_flow_folder_for_a_delineated_network(tmp_path) -> None:
    _write_network_rasters(tmp_path, (5, 5))
    mesh = _mesh(5, 5, np.full(25, 10.0))
    geographic = SimpleNamespace(correcflow_path=str(tmp_path))
    delineated = _model({"net0": {"reach_trace": object()}}, geographic=geographic)
    explicit = _model({"net0": {"reaches": [object()]}}, geographic=geographic)

    tree = build._channel_tree(delineated, mesh)

    assert tree is not None
    assert np.argwhere(tree.link).tolist() == [[2, 1], [2, 2], [2, 3]]
    assert build._channel_tree(explicit, mesh) is None


def test_a_network_traced_on_a_burned_dem_pins_nothing(tmp_path, caplog) -> None:
    _write_network_rasters(tmp_path, (5, 5))
    mesh = _mesh(5, 5, np.full(25, 10.0))
    burned = SimpleNamespace(correcflow_path=str(tmp_path), stream_burn_enabled=True)
    delineated = _model({"net0": {"reach_trace": object()}}, geographic=burned)

    with caplog.at_level("INFO"):
        tree = build._channel_tree(delineated, mesh)

    assert tree is None
    assert "burned observed network" in caplog.text
