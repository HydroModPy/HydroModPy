"""The ground files: the notch read from the config, its report and its footprint on disk."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.catchment.algorithms.ground_corrections import (
    GROUND_FILENAME,
    close_notch_report,
    first_pass_channel,
    ground_dem_from_config,
    ground_dem_path_from_config,
    notch_footprint_path,
    notch_lowered_pixels,
    notch_report_path,
)
from tests._helpers import ground_bench as bench
from tests._helpers.geographic_cases import bench_project, read_band, write_features

ROW = 10


def _road():
    return bench.structures(("road", bench.road_along(ROW)))


def test_a_crossings_file_is_notched_and_its_report_and_footprint_written(tmp_path) -> None:
    project = bench_project(tmp_path, _road())
    setup = project.setup
    assert notch_lowered_pixels(setup) == 0
    ground = ground_dem_from_config(project.config, setup, channel=project.channel)
    assert ground == Path(setup.paths.correcflow_path) / GROUND_FILENAME
    assert ground_dem_path_from_config(project.config, setup) == str(ground)
    notched = read_band(ground)
    assert notched[ROW, bench.AXIS] == pytest.approx(bench.bed(ROW))
    assert np.argwhere(notched != project.valley.dem).tolist() == [[ROW, bench.AXIS]]
    assert np.argwhere(read_band(notch_footprint_path(setup)) > 0).tolist() == [[ROW, bench.AXIS]]
    assert notch_lowered_pixels(setup) == 1
    document = json.loads(notch_report_path(setup).read_text(encoding="utf-8"))
    assert document["parameters"]["path"] == str(project.config.crossings.path)
    assert document["catchment_area_km2_before"] == 1.0
    report = close_notch_report(setup, catchment_area_km2_after=0.9)
    assert report.catchment_area_km2_after == 0.9
    assert "catchment 1.000 -> 0.900 km2" in report.info_line()
    assert json.loads(notch_report_path(setup).read_text())["catchment_area_km2_after"] == 0.9


@pytest.mark.parametrize(
    ("path", "error", "reason"),
    [
        (None, ValueError, "enabled without a path"),
        ("gone.gpkg", FileNotFoundError, "points to nothing"),
        ("no_crs.gpkg", ValueError, "carries no CRS"),
    ],
    ids=["no path", "missing file", "no crs"],
)
@pytest.mark.filterwarnings("ignore:'crs' was not provided")
def test_a_crossings_file_that_cannot_be_placed_is_refused(tmp_path, path, error, reason) -> None:
    project = bench_project(tmp_path, None)
    if path == "no_crs.gpkg":
        _road().set_crs(None, allow_override=True).to_file(tmp_path / path, driver="GPKG")
    project.config.crossings.path = None if path is None else tmp_path / path
    with pytest.raises(error, match=reason):
        ground_dem_from_config(project.config, project.setup, channel=project.channel)


def test_without_the_notch_or_a_first_channel_the_ground_is_the_raw_dem(tmp_path) -> None:
    project = bench_project(tmp_path, _road())
    raw = Path(project.setup.dem_init_path)
    assert ground_dem_from_config(project.config, project.setup) == raw
    project.config.crossings.enabled = False
    assert ground_dem_from_config(project.config, project.setup, channel=project.channel) == raw
    assert ground_dem_path_from_config(project.config, project.setup) == str(raw)


def test_a_declared_lake_on_the_chain_stops_the_notch_read_from_the_config(tmp_path) -> None:
    lake = box(bench.x_of(bench.AXIS - 4), bench.y_of(ROW - 1), bench.x_of(bench.AXIS + 4), 199.0)
    lakes = write_features(tmp_path / "data" / "lake_geometry" / "lakes.gpkg", [lake])
    project = bench_project(tmp_path, _road(), lakes=Path(lakes.name))
    ground = ground_dem_from_config(project.config, project.setup, channel=project.channel)
    assert np.array_equal(read_band(ground), project.valley.dem)
    assert notch_lowered_pixels(project.setup) == 0


@pytest.mark.parametrize("prune", [False, True])
def test_the_first_channel_is_the_pruned_stream_raster_when_pruning(tmp_path, prune) -> None:
    project = bench_project(tmp_path, None, prune=prune)
    flow = SimpleNamespace(direc="d8.tif", acc="acc.tif")
    river = SimpleNamespace(hydrographic_network_generated_shp="river_network.shp")
    channel = first_pass_channel(
        project.config, project.setup, flow=flow, river_products=river, catchment_area_km2=2
    )
    assert channel.streams_tif == project.channel.streams_tif
    assert (channel.d8_tif, channel.acc_tif) == ("d8.tif", "acc.tif")
    assert (channel.network_shp, channel.catchment_area_km2) == ("river_network.shp", 2.0)
