"""The MF6 build builds D for every run, leaves it beside the model, hands it on.

D is seeded on the CHD cells, which keep their receiver while the SFR walks
stop there, with or without SFR, and pinned on the generated network A
whenever the run has A. An auxiliary model builds D only for its SFR walks
and leaves no sidecar. ``resolve_sfr_networks`` traces
a rectified channel on it and prunes its stubs on shared faces. The basin of
D closes on the snapped outlet, falls back on the watershed polygon, warns on
a large gap, and is left in the sidecar with D.
"""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.transform import from_origin

from hydromodpy.catchment.drainage.channel_tree import (
    ChannelExits,
    ChannelTree,
    channel_exits,
    read_channel_tree,
)
from hydromodpy.catchment.terrain.port import D8_WBT_OFFSETS
from hydromodpy.mesh.cells.zonal_stats import rasterize_cell_ids
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.domain.geometry import ChannelRasters, channel_rasters_for_run
from hydromodpy.model.sinks_sources.sfr import FlowReachConfig, FlowReachNetworkConfig
from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow6.builders import sfr as sfr_builder
from hydromodpy.solver.modflow6.builders.sfr import resolve_sfr_networks
from hydromodpy.solver.modflow_common import catchment_basin
from hydromodpy.solver.modflow_common.catchment_basin import run_basin
from hydromodpy.solver.modflow_common.descent_store import read_descent_sidecar
from hydromodpy.solver.modflow_common.flow_directions import (
    build_solver_mesh_descent,
    channel_exits_for_build,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import geometry_of
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

_CODE_OF_STEP = {step: code for code, step in D8_WBT_OFFSETS.items()}


def _mesh(nrow: int, ncol: int, top: np.ndarray) -> SolverMesh:
    """10 m cells; mesh row 0 is the NORTH row, cell id ``row * ncol + col``."""
    return solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.asarray(top, dtype=float).reshape(nrow, ncol),
        botm=np.full((1, nrow, ncol), -50.0),
        dx=10.0,
        dy=10.0,
    )


def _exits_on(mesh: SolverMesh, tree: ChannelTree) -> ChannelExits:
    """A read on the cells of ``mesh``, the way ``prepare_solver`` reads it."""
    labels = rasterize_cell_ids(
        mesh.planar_mesh, transform=tree.transform, out_shape=tree.link.shape
    )
    return channel_exits(tree, labels, n_cells=int(mesh.n_cells))


def _read_on(mesh: SolverMesh, rasters: ChannelRasters) -> ChannelExits:
    """A read from the rasters of a run on a window around ``mesh``, as ``prepare_solver`` does."""
    vertices = np.asarray(mesh.planar_mesh.vertices, dtype=float)[:, :2]
    tree = read_channel_tree(
        link_tif=rasters.link,
        pointer_tif=rasters.pointer,
        accumulation_tif=rasters.accumulation,
        bounds=(*vertices.min(axis=0).tolist(), *vertices.max(axis=0).tolist()),
    )
    return _exits_on(mesh, tree)


def _model(sfr: dict, **extra) -> SimpleNamespace:
    return SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("sfr",)), sfr=sfr
        ),
        **extra,
    )


def _no_chd(n: int) -> dict:
    return {
        "_ocean_support_mask": np.zeros(n, dtype=bool),
        "_stream_support_mask": np.zeros(n, dtype=bool),
    }


def test_route_drainage_builds_d_seeded_on_the_chd_cells(tmp_path) -> None:
    n = 7
    rows, cols = np.divmod(np.arange(n * n), n)
    mesh = _mesh(n, n, 10.0 + rows + cols)
    ocean = np.zeros(n * n, dtype=bool)
    river = np.zeros(n * n, dtype=bool)
    ocean[3 * n + 3] = True
    river[5 * n + 2] = True
    side = {0: [[0, 6 * n + 6, 1.0]], 1: [[0, 6 * n + 5, 1.0]]}
    model = _model(
        {"net0": {"route_drainage": True}},
        full_path=str(tmp_path),
        model_output_name="model",
    )

    constant_head = build._constant_head_cells(n * n, ocean, river, side_chd_spd=side)
    descent = build._run_descent(model, mesh, {}, constant_head)

    assert np.flatnonzero(descent.constant_head).tolist() == [
        3 * n + 3,
        5 * n + 2,
        6 * n + 5,
        6 * n + 6,
    ]
    for cell in (3 * n + 3, 5 * n + 2):
        assert descent.base_level[cell]
        assert descent.receiver[cell] >= 0
        assert descent.stopping_receiver[cell] == -1
    assert not descent.pinned.any()


def test_an_auxiliary_model_builds_no_d_unless_an_sfr_network_walks_it(tmp_path) -> None:
    n = 5
    rows, cols = np.divmod(np.arange(n * n), n)
    mesh = _mesh(n, n, 10.0 + rows + cols)
    none = np.zeros(n * n, dtype=bool)
    quiet = SimpleNamespace(
        inputs=make_model(boundaries=BoundaryConditionBundle(conditions={}, active_ids=())),
        full_path=str(tmp_path / "quiet"),
        model_output_name="ssic",
        auxiliary=True,
    )
    walking = _model(
        {"net0": {"route_drainage": True}},
        full_path=str(tmp_path / "walking"),
        model_output_name="ssic",
        auxiliary=True,
    )

    assert build._run_descent(quiet, mesh, {}, none) is None
    walked = build._run_descent(walking, mesh, {}, none)
    assert walked is not None
    build._keep_dam_feet_and_leave_descent(quiet, None, {}, basin=None)
    walked_basin = run_basin(None, mesh, walked)
    build._keep_dam_feet_and_leave_descent(walking, walked, {"lake": 3}, basin=walked_basin)
    assert quiet.dam_foot_cells == walking.dam_foot_cells == {}
    assert not list(tmp_path.rglob("*.descent.npz"))


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
    mesh = _mesh(nrow, ncol, 50.0 - rows - cols)
    descent = build_solver_mesh_descent(
        mesh,
        lake_cells_by_lake={},
        base_level_mask=None,
        channel_exits=_exits_on(mesh, _staircase_tree(nrow, ncol, path)),
    )
    staircase = [r * ncol + c for r, c in path]
    head_row, head_col = divmod(staircase[0], ncol)
    model = _model({"net0": _rectify_payload(head_row, head_col)})

    networks = resolve_sfr_networks(model, solver_mesh=mesh, descent=descent)

    reach_cells = {int(reach.cellid[1]) for reach in networks["net0"].reaches}
    assert set(staircase) <= reach_cells


def _two_valleys(nrow: int = 10, ncol: int = 10) -> SolverMesh:
    """Two valleys running south, centered on columns 2 and 7."""
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    centre = np.where(cols < 5, 2, 7)
    return _mesh(nrow, ncol, 100.0 + 0.5 * (nrow - 1 - rows) + np.abs(cols - centre))


def _xy(row: int, col: int, nrow: int = 10) -> tuple[float, float]:
    """Center of a mesh cell: row 0 is the northern row, the grid's south edge is y = 0."""
    return (10.0 * col + 5.0, 10.0 * (nrow - 1 - row) + 5.0)


def test_without_an_outlet_the_basin_closes_inside_the_polygon(monkeypatch, caplog) -> None:
    mesh = _two_valleys()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    east = mesh.cell_centers()[:, 0] > 50.0
    monkeypatch.setattr(catchment_basin, "polygon_cell_mask", lambda geographic, centroids: east)

    with caplog.at_level(logging.INFO):
        basin = run_basin(None, mesh, descent)

    assert basin.rule == "within_polygon"
    assert basin.mask[5 * 10 + 7]
    assert not basin.mask[5 * 10 + 2]
    assert "Watershed polygon and basin of D" in caplog.text
    assert caplog.text.count("Basin of D:") == 1


def test_a_basin_far_from_the_polygon_is_a_warning(monkeypatch, caplog) -> None:
    mesh = _two_valleys()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    east = mesh.cell_centers()[:, 0] > 50.0
    monkeypatch.setattr(catchment_basin, "polygon_cell_mask", lambda geographic, centroids: east)
    snapped = _xy(9, 2)
    geographic = SimpleNamespace(x_outlet_snapped=snapped[0], y_outlet_snapped=snapped[1])

    with caplog.at_level(logging.INFO):
        run_basin(geographic, mesh, descent)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Watershed polygon and basin of D" in r.getMessage() for r in warnings)


def test_without_outlet_or_polygon_routing_the_largest_basin_is_a_warning(
    monkeypatch, caplog
) -> None:
    mesh = _two_valleys()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    monkeypatch.setattr(catchment_basin, "polygon_cell_mask", lambda geographic, centroids: None)

    with caplog.at_level(logging.INFO):
        basin = run_basin(None, mesh, descent)
    assert basin.rule == "largest_basin"
    assert not basin.is_catchment
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    with caplog.at_level(logging.INFO):
        mask = sfr_builder._drainage_basin_mask(basin)
    assert mask is basin.mask
    assert any(
        "largest basin of the descent" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING
    )


def test_the_build_keeps_the_basin_and_leaves_it_in_the_sidecar(tmp_path, monkeypatch) -> None:
    mesh = _two_valleys()
    monkeypatch.setattr(catchment_basin, "polygon_cell_mask", lambda geographic, centroids: None)
    declared = _xy(9, 7)
    model = SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=()),
            geometry=geometry_of(SimpleNamespace(x_outlet=declared[0], y_outlet=declared[1])),
        ),
        full_path=str(tmp_path),
        model_output_name="model",
    )

    descent, basin, seeds = build._build_descent_and_dam_feet(
        model, mesh, {}, np.zeros(mesh.n_cells, dtype=bool), None
    )

    assert descent is not None and basin is not None and seeds == {}
    record = read_descent_sidecar(tmp_path / "model.descent.npz")
    assert record is not None
    np.testing.assert_array_equal(record.basin, basin.mask)
    assert record.basin_outlet == basin.outlet
    assert record.basin_rule == "near_point"
    assert record.basin_area_m2 == pytest.approx(basin.area_m2)
    assert record.basin_seeded_at_outlet is False


def _write_network_rasters(folder, shape: tuple[int, int], *, stale: bool = False) -> None:
    """A along row 2, its pointer and accumulation.

    ``stale`` adds a fresh stream raster along row 3 and dates the link raster
    before it: an earlier configuration with links on left it there.
    """
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
        ("dem_direc.tif", np.full(shape, _CODE_OF_STEP[(0, 1)], dtype=np.int32)),
        ("dem_acc_cells.tif", np.tile(np.arange(shape[1], dtype=np.float32), (shape[0], 1))),
        ("dem_stream_link_id_full.tif", link),
    ):
        with rasterio.open(folder / name, "w", dtype=data.dtype, **profile) as dst:
            dst.write(data, 1)
    if not stale:
        return
    streams = np.zeros(shape, dtype=np.int32)
    streams[3, 1:4] = 1
    with rasterio.open(folder / "dem_streams_full.tif", "w", dtype=streams.dtype, **profile) as dst:
        dst.write(streams, 1)
    link_time = os.path.getmtime(folder / "dem_streams_full.tif") - 60.0
    os.utime(folder / "dem_stream_link_id_full.tif", (link_time, link_time))


def test_a_run_without_the_river_network_rasters_pins_nothing(tmp_path, caplog) -> None:
    geographic = SimpleNamespace(correcflow_path=str(tmp_path), river_network_enabled=True)

    with caplog.at_level("INFO"):
        assert channel_exits_for_build(channel_rasters_for_run(geographic), None) is None
    assert "No generated river network A" in caplog.text
    with pytest.raises(FileNotFoundError, match="rasters are missing"):
        channel_exits_for_build(channel_rasters_for_run(geographic), None, required=True)


def test_a_link_raster_older_than_the_stream_raster_is_never_read(tmp_path) -> None:
    _write_network_rasters(tmp_path, (5, 5), stale=True)
    mesh = _mesh(5, 5, np.full(25, 10.0))
    geographic = SimpleNamespace(correcflow_path=str(tmp_path), river_network_enabled=True)

    rasters = channel_rasters_for_run(geographic)
    exits = _read_on(mesh, rasters)

    for required in (False, True):
        assert channel_exits_for_build(rasters, exits, required=required) is exits
    assert np.flatnonzero(exits.holds_a).tolist() == [16, 17, 18]


def _write_streams(path, shape: tuple[int, int], row: int, *, age_s: float = 0.0) -> None:
    """A stream raster with one reach along ``row``, dated ``age_s`` seconds ago."""
    import rasterio

    data = np.zeros(shape, dtype=np.int32)
    data[row, 1:4] = 1
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=shape[0],
        width=shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:2154",
        transform=from_origin(0.0, 10.0 * shape[0], 10.0, 10.0),
    ) as dst:
        dst.write(data, 1)
    if age_s:
        moment = os.path.getmtime(path) - age_s
        os.utime(path, (moment, moment))


def test_the_zonal_channel_mask_reads_the_same_raster_as_the_projection(tmp_path) -> None:
    for name, row, age in (
        ("dem_streams_full.tif", 1, 120.0),
        ("dem_streams_pruned_full.tif", 3, 0.0),
    ):
        _write_streams(tmp_path / name, (5, 5), row, age_s=age)
    support = SimpleNamespace(xmin=0.0, xmax=50.0, ymin=0.0, ymax=50.0, nrows=5, ncols=5, crs=None)
    model = SimpleNamespace(
        modflow_config=SimpleNamespace(
            sgrid=SimpleNamespace(
                top_sampling=SimpleNamespace(
                    mode="zonal", channel_source="streams_raster", channel_buffer_px=0
                )
            )
        ),
        inputs=make_model(
            geometry=geometry_of(
                SimpleNamespace(correcflow_path=str(tmp_path)),
                domain=SimpleNamespace(surface_topo=SimpleNamespace(support=support)),
            )
        ),
    )

    mask = build._resolve_channel_mask_for_zonal(model)

    assert mask is not None
    assert np.argwhere(mask).tolist() == [[3, 1], [3, 2], [3, 3]]
