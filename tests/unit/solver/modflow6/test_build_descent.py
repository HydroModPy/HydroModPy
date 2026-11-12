"""The MODFLOW 6 build derives the descent D and the channel mask from the mesh (cells of 10 m).

D is seeded on the constant-head cells, pinned on the generated river network A when the
run has one, and left in a sidecar with its basin and the dam feet (cell ids). The basin
of D closes on the snapped outlet, falls back on the watershed polygon, or on the largest
basin. The zonal channel mask is read from the stream raster (pixels of 10 or 25 m).
"""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.catchment.drainage.channel_tree import (
    ChannelExits,
    ChannelTree,
    channel_exits,
    read_channel_tree,
)
from hydromodpy.catchment.drainage.descent import descent_basin
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
from hydromodpy.solver.modflow_common.descent_store import (
    read_descent_sidecar,
    write_descent_sidecar,
)
from hydromodpy.solver.modflow_common.flow_directions import (
    build_solver_mesh_descent,
    channel_exits_for_build,
)
from hydromodpy.solver.modflow_grid.sgrid_config import TopSamplingConfig
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.descent_cases import grid_descent
from tests._helpers.mf6_toy_models import geometry_of
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

CODE_OF_STEP = {step: code for code, step in D8_WBT_OFFSETS.items()}
CELL_M = 10.0
NO_DATA = -32768


def tilted_mesh(nrow: int, ncol: int, top: np.ndarray) -> SolverMesh:
    """Cells of 10 m. Mesh row 0 is the north row, the cell id is row * ncol + col."""
    return solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.asarray(top, dtype=float).reshape(nrow, ncol),
        botm=np.full((1, nrow, ncol), -50.0),
        dx=CELL_M,
        dy=CELL_M,
    )


def sloping_mesh(n: int) -> SolverMesh:
    """A square mesh whose ground falls toward the north-west corner."""
    rows, cols = np.divmod(np.arange(n * n), n)
    return tilted_mesh(n, n, 10.0 + rows + cols)


def two_valleys(nrow: int = 10, ncol: int = 10) -> SolverMesh:
    """Two valleys running south, centered on columns 2 and 7."""
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    centre = np.where(cols < 5, 2, 7)
    return tilted_mesh(nrow, ncol, 100.0 + 0.5 * (nrow - 1 - rows) + np.abs(cols - centre))


def cell_xy(row: int, col: int, nrow: int = 10) -> tuple[float, float]:
    """Center of a mesh cell (m). Row 0 is the north row, the south edge is y = 0."""
    return (CELL_M * col + 5.0, CELL_M * (nrow - 1 - row) + 5.0)


def sfr_model(sfr: dict, **extra) -> SimpleNamespace:
    return SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("sfr",)), sfr=sfr
        ),
        **extra,
    )


def walking_sfr_model(folder, name: str = "model", **extra) -> SimpleNamespace:
    return sfr_model(
        {"net0": {"route_drainage": True}},
        full_path=str(folder),
        model_output_name=name,
        **extra,
    )


def exits_on(mesh: SolverMesh, tree: ChannelTree) -> ChannelExits:
    labels = rasterize_cell_ids(
        mesh.planar_mesh, transform=tree.transform, out_shape=tree.link.shape
    )
    return channel_exits(tree, labels, n_cells=int(mesh.n_cells))


def staircase_tree(nrow: int, ncol: int, path: list[tuple[int, int]]) -> ChannelTree:
    link = np.zeros((nrow, ncol), dtype=bool)
    pointer = np.zeros((nrow, ncol), dtype=np.int64)
    accumulation = np.ones((nrow, ncol))
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
        transform=from_origin(0.0, CELL_M * nrow, CELL_M, CELL_M),
    )


def rectify_payload(row: int, col: int) -> FlowReachNetworkConfig:
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


def write_raster(path, data, *, origin, pixel_m, nodata=None, age_s=0.0) -> None:
    """A GeoTIFF in EPSG:2154 whose file date is `age_s` seconds in the past."""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        nodata=nodata,
        crs="EPSG:2154",
        transform=from_origin(origin[0], origin[1], pixel_m, pixel_m),
    ) as dst:
        dst.write(data, 1)
    if age_s:
        moment = os.path.getmtime(path) - age_s
        os.utime(path, (moment, moment))


def write_network_rasters(folder, shape: tuple[int, int], *, stale: bool = False) -> None:
    """The river network A along row 2: pointer, accumulation and link rasters.

    A stale run adds a fresh stream raster along row 3 and dates the link raster
    before it, as an earlier configuration with links on would have left it.
    """
    profile = {
        "driver": "GTiff",
        "height": shape[0],
        "width": shape[1],
        "count": 1,
        "transform": from_origin(0.0, CELL_M * shape[0], CELL_M, CELL_M),
    }
    link = np.zeros(shape, dtype=np.int32)
    link[2, 1:4] = 1
    for name, data in (
        ("dem_direc.tif", np.full(shape, CODE_OF_STEP[(0, 1)], dtype=np.int32)),
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


def read_exits_on(mesh: SolverMesh, rasters: ChannelRasters) -> ChannelExits:
    """Read the rasters of a run on a window around the mesh, as prepare_solver does."""
    vertices = np.asarray(mesh.planar_mesh.vertices, dtype=float)[:, :2]
    tree = read_channel_tree(
        link_tif=rasters.link,
        pointer_tif=rasters.pointer,
        accumulation_tif=rasters.accumulation,
        bounds=(*vertices.min(axis=0).tolist(), *vertices.max(axis=0).tolist()),
    )
    return exits_on(mesh, tree)


def zonal_model(geographic, support, **top_sampling) -> SimpleNamespace:
    return SimpleNamespace(
        modflow_config=SimpleNamespace(
            sgrid=SimpleNamespace(top_sampling=TopSamplingConfig(mode="zonal", **top_sampling))
        ),
        inputs=make_model(
            geometry=geometry_of(
                geographic, domain=SimpleNamespace(surface_topo=SimpleNamespace(support=support))
            )
        ),
    )


def valley_with_lake() -> object:
    """A 7 x 14 valley whose axis (row 3) holds a sill, a pit, a dam and a lake in cols 6 to 9."""
    axis, n_rows, n_cols = 3, 7, 14
    rows, _ = np.meshgrid(np.arange(n_rows), np.arange(n_cols), indexing="ij")
    top = 10.0 + 3.0 * np.abs(rows - axis)
    top[axis] = [0.0, 1.0, 2.0, 6.0, 3.0, 5.0, 4.0, 3.0, 3.5, 4.5, 8.0, 9.0, 10.0, 11.0]
    lake_of = np.full(n_rows * n_cols, -1, dtype=int)
    lake_of[[axis * n_cols + col for col in (6, 7, 8, 9)]] = 0
    return grid_descent(top, lake_of=lake_of)


def keep_dam_feet(model, descent, feet) -> None:
    basin = descent_basin(descent, cell_area_m2=np.ones(descent.receiver.size))
    build._keep_dam_feet_and_leave_descent(model, descent, feet, basin=basin)


def test_descent_seeded_on_constant_head(tmp_path) -> None:
    n = 7
    mesh = sloping_mesh(n)
    ocean = np.zeros(n * n, dtype=bool)
    river = np.zeros(n * n, dtype=bool)
    ocean[3 * n + 3] = True
    river[5 * n + 2] = True
    side = {0: [[0, 6 * n + 6, 1.0]], 1: [[0, 6 * n + 5, 1.0]]}
    model = walking_sfr_model(tmp_path)

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


def test_auxiliary_model_descent(tmp_path) -> None:
    mesh = sloping_mesh(5)
    none = np.zeros(25, dtype=bool)
    quiet = SimpleNamespace(
        inputs=make_model(boundaries=BoundaryConditionBundle(conditions={}, active_ids=())),
        full_path=str(tmp_path / "quiet"),
        model_output_name="ssic",
        auxiliary=True,
    )
    walking = walking_sfr_model(tmp_path / "walking", "ssic", auxiliary=True)

    assert build._run_descent(quiet, mesh, {}, none) is None
    walked = build._run_descent(walking, mesh, {}, none)
    assert walked is not None
    build._keep_dam_feet_and_leave_descent(quiet, None, {}, basin=None)
    walked_basin = run_basin(None, mesh, walked)
    build._keep_dam_feet_and_leave_descent(walking, walked, {"lake": 3}, basin=walked_basin)
    assert quiet.dam_foot_cells == walking.dam_foot_cells == {}
    assert not list(tmp_path.rglob("*.descent.npz"))


def test_rectify_without_descent_refused() -> None:
    mesh = tilted_mesh(5, 5, np.full(25, 10.0))
    model = sfr_model({"net0": rectify_payload(2, 2)})

    with pytest.raises(ValueError, match=r"net0\.rectify_on_mesh"):
        resolve_sfr_networks(model, solver_mesh=mesh)


def test_rectify_keeps_a_lone_staircase() -> None:
    # A staircase of 11 cells on an 8 x 8 grid, pinned in D. On D's D8 adjacency
    # the head of the staircase would read as a stub beside its own channel.
    nrow = ncol = 8
    path = [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4), (4, 5), (5, 5), (5, 6), (6, 6)]
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    mesh = tilted_mesh(nrow, ncol, 50.0 - rows - cols)
    descent = build_solver_mesh_descent(
        mesh,
        lake_cells_by_lake={},
        base_level_mask=None,
        channel_exits=exits_on(mesh, staircase_tree(nrow, ncol, path)),
    )
    staircase = [r * ncol + c for r, c in path]
    model = sfr_model({"net0": rectify_payload(*divmod(staircase[0], ncol))})

    networks = resolve_sfr_networks(model, solver_mesh=mesh, descent=descent)

    reach_cells = {int(reach.cellid[1]) for reach in networks["net0"].reaches}
    assert set(staircase) <= reach_cells


def test_basin_without_outlet_in_polygon(monkeypatch, caplog) -> None:
    mesh = two_valleys()
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


def test_basin_far_from_polygon_warns(monkeypatch, caplog) -> None:
    mesh = two_valleys()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    east = mesh.cell_centers()[:, 0] > 50.0
    monkeypatch.setattr(catchment_basin, "polygon_cell_mask", lambda geographic, centroids: east)
    x_m, y_m = cell_xy(9, 2)
    geographic = SimpleNamespace(x_outlet_snapped=x_m, y_outlet_snapped=y_m)

    with caplog.at_level(logging.INFO):
        run_basin(geographic, mesh, descent)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Watershed polygon and basin of D" in r.getMessage() for r in warnings)


def test_largest_basin_warns(monkeypatch, caplog) -> None:
    mesh = two_valleys()
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


def test_basin_left_in_sidecar(tmp_path, monkeypatch) -> None:
    mesh = two_valleys()
    monkeypatch.setattr(catchment_basin, "polygon_cell_mask", lambda geographic, centroids: None)
    x_m, y_m = cell_xy(9, 7)
    model = SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=()),
            geometry=geometry_of(SimpleNamespace(x_outlet=x_m, y_outlet=y_m)),
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


def test_missing_network_rasters_pin_nothing(tmp_path, caplog) -> None:
    geographic = SimpleNamespace(correcflow_path=str(tmp_path), river_network_enabled=True)

    with caplog.at_level("INFO"):
        assert channel_exits_for_build(channel_rasters_for_run(geographic), None) is None
    assert "No generated river network A" in caplog.text
    with pytest.raises(FileNotFoundError, match="rasters are missing"):
        channel_exits_for_build(channel_rasters_for_run(geographic), None, required=True)


def test_stale_link_raster_never_read(tmp_path) -> None:
    write_network_rasters(tmp_path, (5, 5), stale=True)
    mesh = tilted_mesh(5, 5, np.full(25, 10.0))
    geographic = SimpleNamespace(correcflow_path=str(tmp_path), river_network_enabled=True)

    rasters = channel_rasters_for_run(geographic)
    exits = read_exits_on(mesh, rasters)

    for required in (False, True):
        assert channel_exits_for_build(rasters, exits, required=required) is exits
    assert np.flatnonzero(exits.holds_a).tolist() == [16, 17, 18]


def test_auxiliary_model_keeps_no_foot(tmp_path) -> None:
    model = SimpleNamespace(full_path=str(tmp_path), model_output_name="model", auxiliary=True)

    keep_dam_feet(model, valley_with_lake(), {"reservoir": 3})

    assert model.dam_foot_cells == {}
    assert not list(tmp_path.glob("*.descent.npz"))


def test_old_sidecar_has_no_feet(tmp_path) -> None:
    path = write_descent_sidecar(valley_with_lake(), tmp_path, "model", dam_foot_cells={"a": 12})
    with np.load(path) as payload:
        kept = {name: payload[name] for name in payload.files if name != "dam_foot"}
    np.savez(path, **kept)

    record = read_descent_sidecar(path)

    assert record is not None
    assert record.dam_foot.size == 0


def test_zonal_mask_holds_stream_pixels(tmp_path) -> None:
    # GDAL moves a valid pixel equal to the destination nodata to the next float.
    # With a destination nodata of 0 the background of a stream raster became 5e-324
    # and the channel class covered the whole catchment.
    links = np.zeros((20, 20), dtype=np.int32)
    links[:2, :] = NO_DATA  # outside the catchment
    links[10, 3:9] = 185  # one reach of six pixels
    path = tmp_path / "river_stream_link_id.tif"
    write_raster(path, links, origin=(1000.0, 2000.0), pixel_m=25.0, nodata=NO_DATA)
    # A wider support than the stream raster, so the reprojection really resamples.
    support = SimpleNamespace(
        xmin=950.0, xmax=1550.0, ymin=1450.0, ymax=2050.0, nrows=24, ncols=24, crs="EPSG:2154"
    )
    geographic = SimpleNamespace(river_stream_link_id_tif=str(path), river_streams_tif=None)

    mask = build._resolve_channel_mask_for_zonal(zonal_model(geographic, support))

    assert mask is not None
    assert int(mask.sum()) == 6


def test_zonal_mask_falls_back_to_streams_full(tmp_path) -> None:
    links = np.zeros((20, 20), dtype=np.int32)
    links[5, 2:6] = 1
    write_raster(tmp_path / "dem_streams_full.tif", links, origin=(1000.0, 2000.0), pixel_m=25.0)
    support = SimpleNamespace(
        xmin=1000.0, xmax=1500.0, ymin=1500.0, ymax=2000.0, nrows=20, ncols=20, crs="EPSG:2154"
    )
    geographic = SimpleNamespace(
        river_stream_link_id_tif=None, river_streams_tif=None, correcflow_path=str(tmp_path)
    )

    mask = build._resolve_channel_mask_for_zonal(zonal_model(geographic, support))

    assert int(mask.sum()) == 4


def test_zonal_mask_reads_projection_raster(tmp_path) -> None:
    # The older stream raster has its reach in row 1, the pruned one in row 3.
    for name, row, age in (
        ("dem_streams_full.tif", 1, 120.0),
        ("dem_streams_pruned_full.tif", 3, 0.0),
    ):
        data = np.zeros((5, 5), dtype=np.int32)
        data[row, 1:4] = 1
        write_raster(tmp_path / name, data, origin=(0.0, 50.0), pixel_m=CELL_M, age_s=age)
    support = SimpleNamespace(xmin=0.0, xmax=50.0, ymin=0.0, ymax=50.0, nrows=5, ncols=5, crs=None)
    geographic = SimpleNamespace(correcflow_path=str(tmp_path))
    model = zonal_model(geographic, support, channel_source="streams_raster", channel_buffer_px=0)

    mask = build._resolve_channel_mask_for_zonal(model)

    assert mask is not None
    assert np.argwhere(mask).tolist() == [[3, 1], [3, 2], [3, 3]]
