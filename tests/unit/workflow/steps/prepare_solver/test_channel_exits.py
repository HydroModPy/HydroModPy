"""``step_build_model`` reads the river network A on the cells of the mesh, when the run has one.

A is read when the river network step ran for the run, or when an SFR network was
delineated from it, and the three rasters exist. A backend that needs A and finds
none says so itself, so a missing raster here is not an error. The rasters of an
earlier configuration are never read.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.transform import from_origin

from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.workflow.steps.prepare_solver.model import step_build_model
from tests._helpers.regular_cell_meshes import regular_cell_mesh

_XMIN, _YMIN = 350_000.0, 6_800_000.0
LINK = "dem_stream_link_id_full.tif"
STREAMS = "dem_streams_full.tif"
POINTER = "dem_direc.tif"
ACCUMULATION = "dem_acc_cells.tif"
EAST = 2  # the WhiteboxTools D8 code of a step to the east


def _write(path: Path, data: np.ndarray) -> None:
    import rasterio

    # The raster is the mesh (2 x 3 cells of 100 m) with one pixel of margin around it.
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        transform=from_origin(_XMIN - 100.0, _YMIN + 300.0, 100.0, 100.0),
    ) as dst:
        dst.write(data, 1)


def _write_network(folder: Path, *, link_name: str = LINK) -> None:
    """A along raster row 1, columns 1 to 3: the three cells of the north row of the mesh."""
    link = np.zeros((4, 5), dtype=np.int32)
    link[1, 1:4] = 1
    _write(folder / link_name, link)
    _write(folder / POINTER, np.full((4, 5), EAST, dtype=np.int32))
    _write(folder / ACCUMULATION, np.arange(20, dtype=np.float32).reshape(4, 5))


def _geographic(folder: Path | None, *, enabled: bool = True, **clipped: object):
    return SimpleNamespace(
        correcflow_path=None if folder is None else str(folder),
        river_network_enabled=enabled,
        **clipped,
    )


def _ctx(project: Path, geographic, *, traces=None):
    config = FlowConfig()
    cfg = SimpleNamespace(
        flow=config,
        solver=SolverConfig(),
        geographic=SimpleNamespace(crs_project="EPSG:2154"),
        simulation=SimpleNamespace(),
    )
    setup = SimpleNamespace(
        flow=Flow(config=config),
        cell_mesh=regular_cell_mesh(xmin=_XMIN, ymin=_YMIN, dx=100.0, dy=100.0, nrow=2, ncol=3),
        domain=None,
        geographic=geographic,
        time_grid=None,
        flow_runtime_overrides=None,
        workspace=SimpleNamespace(project_root=project),
        model=None,
        sfr_reach_traces=traces,
    )
    return SimpleNamespace(cfg=cfg, setup=setup, execution=ExecutionRegistry(lightweight=True))


def _exits(project: Path, geographic, *, traces=None):
    return step_build_model(_ctx(project, geographic, traces=traces)).geometry.channel_exits


@pytest.mark.parametrize("traces", [None, {"net0": object()}], ids=["no_traces", "traces"])
def test_the_network_is_read_on_the_cells_of_the_mesh(tmp_path: Path, traces) -> None:
    _write_network(tmp_path)

    exits = _exits(tmp_path, _geographic(tmp_path), traces=traces)

    assert exits is not None and exits.n_cells == 6
    assert np.flatnonzero(exits.holds_a).tolist() == [0, 1, 2]
    assert exits.next_cell[:3].tolist() == [1, 2, -1]
    assert exits.next_on_a[:3].tolist() == [True, True, False]


def test_a_network_an_sfr_network_was_delineated_from_is_read_with_the_step_off(
    tmp_path: Path,
) -> None:
    _write_network(tmp_path)

    exits = _exits(tmp_path, _geographic(tmp_path, enabled=False), traces={"net0": object()})

    assert exits is not None and exits.holds_a.sum() == 3


@pytest.mark.parametrize("traces", [None, {}], ids=["none", "empty"])
def test_rasters_left_by_an_earlier_configuration_are_not_read(tmp_path: Path, traces) -> None:
    _write_network(tmp_path)

    assert _exits(tmp_path, _geographic(tmp_path, enabled=False), traces=traces) is None


@pytest.mark.parametrize("enabled", [True, False])
def test_a_run_without_a_corrected_flow_folder_has_no_exits(tmp_path: Path, enabled: bool) -> None:
    assert _exits(tmp_path, _geographic(None, enabled=enabled), traces={"net0": object()}) is None


def test_a_run_without_a_delineation_has_no_exits(tmp_path: Path) -> None:
    assert _exits(tmp_path, None) is None


def test_missing_rasters_give_no_exits_and_no_error(tmp_path: Path) -> None:
    assert _exits(tmp_path, _geographic(tmp_path), traces={"net0": object()}) is None


def test_the_clipped_rasters_are_never_read_as_the_network(tmp_path: Path) -> None:
    clipped = tmp_path / "clipped.tif"
    _write(clipped, np.ones((4, 5), dtype=np.int32))
    geographic = _geographic(None, river_streams_tif=str(clipped))

    assert _exits(tmp_path, geographic, traces={"net0": object()}) is None


def test_a_link_raster_older_than_the_stream_raster_is_not_the_network(tmp_path: Path) -> None:
    _write_network(tmp_path)
    streams = np.zeros((4, 5), dtype=np.int32)
    streams[2, 1:3] = 1
    _write(tmp_path / STREAMS, streams)
    moment = os.path.getmtime(tmp_path / STREAMS) - 60.0
    os.utime(tmp_path / LINK, (moment, moment))

    exits = _exits(tmp_path, _geographic(tmp_path))

    assert exits is not None
    assert np.flatnonzero(exits.holds_a).tolist() == [3, 4]


def test_a_tree_with_no_pixel_on_the_mesh_gives_exits_that_hold_nothing(tmp_path: Path) -> None:
    _write_network(tmp_path)
    _write(tmp_path / LINK, np.zeros((4, 5), dtype=np.int32))

    exits = _exits(tmp_path, _geographic(tmp_path))

    assert exits is not None and exits.n_cells == 6 and not exits.holds_a.any()
