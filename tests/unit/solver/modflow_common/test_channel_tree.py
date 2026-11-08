"""The rasters of the generated river network A are chosen once, then read around the mesh.

``channel_rasters_for_run`` runs in ``prepare_solver`` and its answer sits in
``Model.geometry.raster.channel``. ``channel_tree_for_run`` reads that answer.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.transform import from_origin

from hydromodpy.model.domain.geometry import ChannelRasters
from hydromodpy.solver.modflow_common.channel_tree import (
    active_channel_raster,
    channel_rasters_for_run,
    channel_tree_for_run,
)
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

SHAPE = (5, 5)
LINK = "dem_stream_link_id_full.tif"
STREAMS = "dem_streams_full.tif"
POINTER = "dem_direc.tif"
ACCUMULATION = "dem_acc_cells.tif"


def _write(path: Path, data: np.ndarray) -> None:
    import rasterio

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=SHAPE[0],
        width=SHAPE[1],
        count=1,
        dtype=data.dtype,
        transform=from_origin(0.0, 10.0 * SHAPE[0], 10.0, 10.0),
    ) as dst:
        dst.write(data, 1)


def _write_network(folder: Path) -> None:
    """A along row 2 of the link raster, with a pointer and an accumulation."""
    link = np.zeros(SHAPE, dtype=np.int32)
    link[2, 1:4] = 1
    _write(folder / LINK, link)
    _write(folder / POINTER, np.ones(SHAPE, dtype=np.int32))
    _write(folder / ACCUMULATION, np.ones(SHAPE, dtype=np.float32))


def _mesh():
    return solver_mesh_from_structured_arrays(
        nrow=SHAPE[0],
        ncol=SHAPE[1],
        top=np.full(SHAPE, 10.0),
        botm=np.full((1, *SHAPE), -50.0),
        dx=10.0,
        dy=10.0,
    )


def _geographic(folder: Path | None = None, *, enabled: bool = True, **clipped: object):
    return SimpleNamespace(
        correcflow_path=None if folder is None else str(folder),
        river_network_enabled=enabled,
        **clipped,
    )


@pytest.mark.parametrize("geographic", [None, SimpleNamespace(), _geographic(enabled=False)])
def test_a_run_without_a_folder_a_clipped_raster_or_the_step_has_no_rasters(geographic) -> None:
    assert channel_rasters_for_run(geographic) is None


def test_a_run_whose_step_ran_but_left_no_folder_says_so() -> None:
    rasters = channel_rasters_for_run(_geographic(enabled=True))

    assert rasters == ChannelRasters(
        enabled=True, link=None, pointer=None, accumulation=None, clipped=()
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_the_three_full_extent_paths_are_named_whether_or_not_the_files_exist(
    tmp_path: Path, enabled: bool
) -> None:
    rasters = channel_rasters_for_run(_geographic(tmp_path, enabled=enabled))

    assert rasters == ChannelRasters(
        enabled=enabled,
        link=str(tmp_path / STREAMS),
        pointer=str(tmp_path / POINTER),
        accumulation=str(tmp_path / ACCUMULATION),
        clipped=(),
    )
    assert rasters.link == active_channel_raster(tmp_path)


def test_the_link_raster_is_the_one_the_rule_of_every_reader_picks(tmp_path: Path) -> None:
    _write_network(tmp_path)

    assert channel_rasters_for_run(_geographic(tmp_path)).link == str(tmp_path / LINK)


def test_only_the_clipped_rasters_that_exist_are_kept_link_first(tmp_path: Path) -> None:
    link, streams = tmp_path / "link.tif", tmp_path / "streams.tif"
    _write(link, np.ones(SHAPE, dtype=np.int32))
    _write(streams, np.ones(SHAPE, dtype=np.int32))
    missing = str(tmp_path / "gone.tif")

    both = channel_rasters_for_run(
        _geographic(river_stream_link_id_tif=str(link), river_streams_tif=str(streams))
    )
    only_streams = channel_rasters_for_run(
        _geographic(river_stream_link_id_tif=missing, river_streams_tif=str(streams))
    )
    none = channel_rasters_for_run(
        _geographic(enabled=False, river_stream_link_id_tif=missing, river_streams_tif=None)
    )

    assert both.clipped == (str(link), str(streams))
    assert only_streams.clipped == (str(streams),)
    assert none is None


def test_the_clipped_rasters_are_never_read_as_the_network(tmp_path: Path) -> None:
    clipped = tmp_path / "clipped.tif"
    _write(clipped, np.ones(SHAPE, dtype=np.int32))
    rasters = channel_rasters_for_run(_geographic(river_streams_tif=str(clipped)))

    assert channel_tree_for_run(rasters, _mesh(), required=True) is None


@pytest.mark.parametrize("required", [False, True])
def test_the_network_is_read_around_the_mesh_with_or_without_the_sfr_need(
    tmp_path: Path, required: bool
) -> None:
    _write_network(tmp_path)
    rasters = channel_rasters_for_run(_geographic(tmp_path))

    tree = channel_tree_for_run(rasters, _mesh(), required=required)

    assert tree is not None
    assert np.argwhere(tree.link).tolist() == [[2, 1], [2, 2], [2, 3]]


@pytest.mark.parametrize(
    ("rasters", "message"),
    [
        (None, "river network is off"),
        (ChannelRasters(False, "a", "b", "c"), "river network is off"),
        (ChannelRasters(True, None, None, None), "No corrected-flow folder"),
    ],
    ids=["no_choice", "step_off", "no_folder"],
)
def test_a_run_that_has_no_network_pins_nothing_and_says_why(
    rasters, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        assert channel_tree_for_run(rasters, _mesh()) is None

    assert message in caplog.text


def test_a_network_that_the_sfr_needs_without_a_folder_pins_nothing_and_says_why(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO"):
        assert channel_tree_for_run(None, _mesh(), required=True) is None

    assert "No corrected-flow folder" in caplog.text


def test_missing_rasters_are_an_error_only_when_the_sfr_lies_on_the_network(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rasters = channel_rasters_for_run(_geographic(tmp_path))

    with caplog.at_level("INFO"):
        assert channel_tree_for_run(rasters, _mesh()) is None
    assert f"No generated river network A in {tmp_path}" in caplog.text
    with pytest.raises(FileNotFoundError, match="rasters are missing"):
        channel_tree_for_run(rasters, _mesh(), required=True)


def test_rasters_left_by_an_earlier_configuration_are_not_read(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write_network(tmp_path)
    rasters = channel_rasters_for_run(_geographic(tmp_path, enabled=False))

    with caplog.at_level("INFO"):
        assert channel_tree_for_run(rasters, _mesh()) is None
    assert "river network is off" in caplog.text


def test_a_link_raster_older_than_the_stream_raster_is_not_the_network(tmp_path: Path) -> None:
    _write_network(tmp_path)
    streams = np.zeros(SHAPE, dtype=np.int32)
    streams[3, 1:4] = 1
    _write(tmp_path / STREAMS, streams)
    moment = os.path.getmtime(tmp_path / STREAMS) - 60.0
    os.utime(tmp_path / LINK, (moment, moment))
    rasters = channel_rasters_for_run(_geographic(tmp_path))

    tree = channel_tree_for_run(rasters, _mesh())

    assert rasters.link == str(tmp_path / STREAMS)
    assert tree is not None
    assert np.argwhere(tree.link).tolist() == [[3, 1], [3, 2], [3, 3]]
