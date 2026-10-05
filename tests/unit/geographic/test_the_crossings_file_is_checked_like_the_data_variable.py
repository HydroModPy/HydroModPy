"""A file named in [geographic.crossings] path meets the checks of the data variable."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest

from hydromodpy.spatial.geographic.core import ground_corrections
from hydromodpy.spatial.geographic.core.ground_corrections import (
    FirstPassChannel,
    ground_dem_from_config,
)
from tests._helpers import ground_bench as bench

ROAD_ROW = 10
HEIGHT = 2.5


def test_a_kind_is_read_stripped_and_in_lower_case() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    crossings = bench.structures((" Road ", bench.road_along(ROAD_ROW)))

    out, report = bench.notch(valley, crossings)

    assert out[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW))
    assert report.features == {"road": 1}


def test_a_kind_that_is_not_one_of_the_six_is_refused_by_name() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    crossings = bench.structures(("route", bench.road_along(ROAD_ROW)))

    with pytest.raises(ValueError, match=r"'kind' value\(s\) \['route'\] are not allowed"):
        bench.notch(valley, crossings)


def test_a_file_without_a_kind_column_is_refused() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    crossings = gpd.GeoDataFrame(geometry=[bench.road_along(ROAD_ROW)], crs=bench.CRS)

    with pytest.raises(ValueError, match="no 'kind' column"):
        bench.notch(valley, crossings)


def test_the_kinds_are_the_ones_of_the_data_variable() -> None:
    from hydromodpy.data.variables.crossings.config import KINDS

    assert tuple(KINDS) == ground_corrections._KINDS


def _ground_from(tmp_path: Path, crossings: gpd.GeoDataFrame):
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    dem = bench.write_raster(tmp_path / "dem.tif", valley.dem)
    streams = bench.write_raster(tmp_path / "streams.tif", valley.streams.astype("float32"))
    d8 = bench.write_raster(tmp_path / "d8.tif", valley.d8, dtype="int32")
    acc = bench.write_raster(tmp_path / "acc.tif", valley.acc)
    network = tmp_path / "network.shp"
    valley.network.to_file(network)
    path = tmp_path / "crossings.gpkg"
    crossings.to_file(path, driver="GPKG")
    config = SimpleNamespace(
        crossings=SimpleNamespace(
            enabled=True,
            path=path,
            kinds=["road", "railway", "bridge"],
            notch_width=10.0,
            bed_reach=30.0,
            max_depth=3.0,
            snap_radius=30.0,
        ),
        dam_carve=SimpleNamespace(enabled=False),
        enforce_lakes=SimpleNamespace(enabled=False),
    )
    setup = SimpleNamespace(
        dem_init_path=str(dem),
        crs_project=bench.CRS,
        paths=SimpleNamespace(correcflow_path=tmp_path / "work"),
    )
    channel = FirstPassChannel(str(streams), str(d8), str(acc), str(network), 1.0)
    return ground_dem_from_config(config, setup, channel=channel)


@pytest.mark.filterwarnings("ignore:'crs' was not provided")
def test_a_file_without_a_crs_is_refused_and_not_taken_for_the_project_crs(tmp_path) -> None:
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))
    without_crs = crossings.set_crs(None, allow_override=True)

    with pytest.raises(ValueError, match="carries no CRS"):
        _ground_from(tmp_path, without_crs)


def test_a_file_with_a_crs_is_notched(tmp_path) -> None:
    ground = _ground_from(tmp_path, bench.structures(("road", bench.road_along(ROAD_ROW))))

    import rasterio

    with rasterio.open(ground) as src:
        notched = src.read(1)
    assert notched[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW))
    assert np.argwhere(notched != bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT).dem).size


def test_a_bridge_of_one_source_and_a_road_of_another_are_one_crossing() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    crossings = bench.structures(
        ("road", bench.road_along(ROAD_ROW)),
        ("bridge", bench.bridge_at(bench.AXIS + 1, ROAD_ROW)),
    )

    out, report = bench.notch(valley, crossings)

    assert sum(report.crossing_points.values()) == 1
    assert sum(report.notched.values()) == 1
    assert report.skipped == {}
    assert out[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW))


def test_a_road_split_in_two_at_the_stream_is_one_crossing() -> None:
    from shapely.geometry import LineString

    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    x, y = bench.x_of(bench.AXIS), bench.y_of(ROAD_ROW)
    crossings = bench.structures(
        ("road", LineString([(0.0, y), (x, y)])),
        ("road", LineString([(x, y), (bench.N * bench.RES, y)])),
    )

    _, report = bench.notch(valley, crossings)

    assert report.crossing_points == {"road": 1}
    assert report.notched == {"road": 1}
    assert report.skipped == {}
