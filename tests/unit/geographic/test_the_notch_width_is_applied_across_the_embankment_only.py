"""notch_width widens the cut across the embankment, never along the channel past it."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import LineString

from hydromodpy.spatial.geographic.core.ground_corrections import NotchReport, notch_dem
from tests._helpers import ground_bench as bench

RES, N, AXIS, ROAD = 5.0, 61, 30, 30
CRS = "EPSG:2154"


def _incised_valley_with_a_wide_embankment():
    """A 5 m DEM: banks 1 m above a concave bed, a 15 m embankment on three rows."""
    transform = from_origin(0.0, N * RES, RES, RES)
    rows, cols = np.arange(N)[:, None], np.arange(N)[None, :]
    bed = 100.0 - 0.05 * rows + 0.0004 * rows**2
    dem = bed + np.where(cols == AXIS, 0.0, 1.0 + 0.2 * np.abs(cols - AXIS))
    dem[ROAD - 1 : ROAD + 2, :] += 2.0
    streams = np.zeros((N, N), bool)
    streams[:, AXIS] = True
    d8 = np.full((N, N), 8, int)
    d8[N - 1, :] = 0
    acc = np.ones((N, N))
    acc[:, AXIS] = np.arange(1, N + 1)
    x = (AXIS + 0.5) * RES
    network = gpd.GeoDataFrame(geometry=[LineString([(x, N * RES - 1), (x, 1)])], crs=CRS)
    y = N * RES - (ROAD + 0.5) * RES
    road = bench.structures(("road", LineString([(0, y), (N * RES, y)])))
    return dem.astype("float32"), transform, streams, d8, acc, network, road


def _notch(width: float):
    dem, transform, streams, d8, acc, network, road = _incised_valley_with_a_wide_embankment()
    report = NotchReport(parameters={})
    out, _ = notch_dem(
        dem,
        nodata=-9999.0,
        transform=transform,
        streams=streams,
        d8=d8,
        acc=acc,
        crossings=road,
        network=network,
        kinds=["road"],
        notch_width_m=width,
        bed_reach_m=50.0,
        max_depth_m=5.0,
        snap_radius_m=30.0,
        report=report,
    )
    return dem, out, report


def test_on_a_five_metre_dem_no_pixel_off_the_embankment_moves() -> None:
    dem, out, _ = _notch(10.0)

    moved = np.argwhere(out < dem - 1e-4)

    assert len(moved) > 0
    assert set(moved[:, 0].tolist()) <= {ROAD - 1, ROAD, ROAD + 1}


def test_the_embankment_and_one_pixel_each_side_fall_to_the_bed_line() -> None:
    dem, out, report = _notch(10.0)

    moved = np.argwhere(out < dem - 1e-4)

    assert set(moved[:, 1].tolist()) == {AXIS - 1, AXIS, AXIS + 1}
    assert report.pixels_lowered == 9


@pytest.mark.parametrize("width", [10.0, 20.0, 40.0])
def test_the_two_end_pixels_are_never_lowered(width: float) -> None:
    dem, out, _ = _notch(width)

    # The reach is 50 m: the ends are ten pixels on each side of the crossing.
    for row in (ROAD - 10, ROAD + 10):
        assert (out[row, :] == dem[row, :]).all()


def test_a_bank_pixel_takes_the_level_of_its_own_position_along_the_channel() -> None:
    dem, out, _ = _notch(10.0)

    # The bed is not a straight line, so the levels differ from row to row.
    levels = [out[row, AXIS - 1] for row in (ROAD - 1, ROAD, ROAD + 1)]
    assert out[ROAD, AXIS] == pytest.approx(out[ROAD, AXIS + 1])
    assert len({round(float(level), 4) for level in levels}) == 3
    assert (out <= dem).all()


def test_a_ten_metre_cell_bench_keeps_its_ends_at_any_width() -> None:
    valley = bench.build(embankment_rows=(10,), height=2.5)
    crossings = bench.structures(("road", bench.road_along(10)))

    out, _ = bench.notch(valley, crossings, notch_width_m=30.0, max_depth_m=5.0)

    # The reach is 30 m: the up end is (7, 10), the pixel beside it (7, 9).
    assert out[7, bench.AXIS] == valley.dem[7, bench.AXIS]
    assert out[7, bench.AXIS - 1] == valley.dem[7, bench.AXIS - 1]
    assert np.argwhere(out != valley.dem)[:, 0].tolist() == [10, 10, 10]
