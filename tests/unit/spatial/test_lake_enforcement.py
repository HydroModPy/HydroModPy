"""Carve lakes into a routing DEM so streams route into them and drain to the outlet."""

from __future__ import annotations

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin, rowcol
from shapely.geometry import box

from hydromodpy.spatial.geographic.core.lake_enforcement import (
    carve_dam_into_top_dem,
    carve_routing_dem,
)

_N = 20
_RES = 10.0
_TRANSFORM = from_origin(0.0, _N * _RES, _RES, _RES)  # top-left (0, 200), 10 m cells
# Terrain sloping from 100 m (north) down to 60 m (south): the outlet sits at the low
# southern edge, the lake is a mid-slope plateau to be carved below its own terrain.
_DEM = np.tile((100.0 - 40.0 * np.arange(_N) / (_N - 1))[:, None], (1, _N)).astype("float32")
_LAKE = box(60.0, 90.0, 120.0, 130.0)


def _write_dem_arr(path: str, arr: np.ndarray) -> None:
    profile = {
        "driver": "GTiff",
        "height": _N,
        "width": _N,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": _TRANSFORM,
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype("float32"), 1)


def _write_dem(path: str) -> None:
    _write_dem_arr(path, _DEM)


def test_carve_makes_lake_a_sink_draining_to_outlet(tmp_path) -> None:
    raw = str(tmp_path / "raw.tif")
    out = str(tmp_path / "routing.tif")
    _write_dem(raw)
    outlet = (190.0, 10.0)  # low SE corner

    rep = carve_routing_dem(
        dem_in_path=raw,
        dem_out_path=out,
        lake_polygons=[_LAKE],
        outlet_xy=outlet,
        slope=0.01,
        buffer_m=5.0,
    )
    with rasterio.open(out) as src:
        carved = src.read(1)

    lake_mask = rasterize(
        [(_LAKE, 1)], out_shape=(_N, _N), transform=_TRANSFORM, fill=0, dtype="uint8"
    ).astype(bool)
    # Every lake cell was carved BELOW its own terrain (a genuine sink).
    assert rep.lake_cells > 0
    assert np.all(carved[lake_mask] < _DEM[lake_mask])
    # An outlet notch was punched so the lake drains out.
    assert rep.notch_cells > 0
    # Never raised the terrain anywhere.
    assert np.all(carved <= _DEM + 1e-4)
    # Monotonic ramp: the lake cell nearest the outlet is lower than the farthest.
    r_near, c_near = rowcol(_TRANSFORM, 118.0, 92.0)  # SE corner (near the outlet)
    r_far, c_far = rowcol(_TRANSFORM, 62.0, 128.0)  # NW corner (far)
    assert carved[r_near, c_near] < carved[r_far, c_far]

    # The raw DEM (the model-top source) is untouched.
    with rasterio.open(raw) as src:
        assert np.allclose(src.read(1), _DEM)


def test_no_outlet_carves_a_sink_without_notch(tmp_path) -> None:
    raw = str(tmp_path / "raw.tif")
    out = str(tmp_path / "routing.tif")
    _write_dem(raw)

    rep = carve_routing_dem(
        dem_in_path=raw,
        dem_out_path=out,
        lake_polygons=[_LAKE],
        outlet_xy=None,
        slope=0.01,
        buffer_m=5.0,
    )
    assert rep.lake_cells > 0
    assert rep.notch_cells == 0  # no outlet -> no notch, the lake is a terminal sink


def _write_int(path: str, arr: np.ndarray) -> None:
    profile = {
        "driver": "GTiff",
        "height": _N,
        "width": _N,
        "count": 1,
        "dtype": "int32",
        "crs": "EPSG:2154",
        "transform": _TRANSFORM,
        "nodata": 0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype("int32"), 1)


def test_capture_carves_a_near_miss_stream_to_the_lake(tmp_path) -> None:
    from hydromodpy.spatial.geographic.core.lake_enforcement import capture_stream_gaps

    dem = np.full((_N, _N), 90.0, dtype="float32")
    lake = box(140.0, 60.0, 180.0, 120.0)  # a low lake to the east
    lake_mask = rasterize(
        [(lake, 1)], out_shape=(_N, _N), transform=_TRANSFORM, fill=0, dtype="uint8"
    ).astype(bool)
    dem[lake_mask] = 65.0
    routing = str(tmp_path / "routing.tif")
    _write_dem_arr(routing, dem)

    # A stream (link 1) along row 10, cols 2..8, each cell flowing East (D8 code 1).
    # Cell (10,8) is a near-miss terminal: its downstream (10,9) is neither stream nor
    # lake, so the extracted channel dead-ends ~60 m short of the lake.
    link = np.zeros((_N, _N), dtype="int32")
    link[10, 2:9] = 1
    d8 = np.zeros((_N, _N), dtype="int32")
    d8[10, 2:9] = 1  # East
    link_tif = str(tmp_path / "link.tif")
    d8_tif = str(tmp_path / "d8.tif")
    _write_int(link_tif, link)
    _write_int(d8_tif, d8)

    out = str(tmp_path / "captured.tif")
    rep = capture_stream_gaps(
        dem_path=routing,
        out_path=out,
        link_id_tif=link_tif,
        d8_tif=d8_tif,
        lake_polygons=[lake],
        capture_radius_m=200.0,
        slope=0.01,
        buffer_m=5.0,
    )
    assert rep.near_misses == 1
    assert rep.channel_cells > 0
    with rasterio.open(out) as src:
        carved = src.read(1)
    # the gap cells between the stream end and the lake (row 10, cols 9..13) are lowered
    assert np.all(carved[10, 9:14] < 90.0)


def test_capture_skips_a_stream_beyond_the_radius(tmp_path) -> None:
    from hydromodpy.spatial.geographic.core.lake_enforcement import capture_stream_gaps

    dem = np.full((_N, _N), 90.0, dtype="float32")
    lake = box(140.0, 60.0, 180.0, 120.0)
    lake_mask = rasterize(
        [(lake, 1)], out_shape=(_N, _N), transform=_TRANSFORM, fill=0, dtype="uint8"
    ).astype(bool)
    dem[lake_mask] = 65.0
    routing = str(tmp_path / "routing.tif")
    _write_dem_arr(routing, dem)
    link = np.zeros((_N, _N), dtype="int32")
    link[10, 0:3] = 1  # a stream far west, terminal at col 2 (~120 m from the lake)
    d8 = np.zeros((_N, _N), dtype="int32")
    d8[10, 0:3] = 1
    link_tif = str(tmp_path / "link.tif")
    d8_tif = str(tmp_path / "d8.tif")
    _write_int(link_tif, link)
    _write_int(d8_tif, d8)
    rep = capture_stream_gaps(
        dem_path=routing,
        out_path=str(tmp_path / "c.tif"),
        link_id_tif=link_tif,
        d8_tif=d8_tif,
        lake_polygons=[lake],
        capture_radius_m=50.0,
        slope=0.01,
        buffer_m=5.0,
    )
    assert rep.near_misses == 0  # the lake is beyond the 50 m capture radius


def test_dam_top_carve_lowers_the_crest_to_the_valley_floor(tmp_path) -> None:
    # A DEM with a concrete dam crest (a high wall) across a low valley: the carve
    # must bring the dam corridor down to the surrounding valley-floor minimum.
    from shapely.geometry import LineString

    valley = np.full((_N, _N), 55.0, dtype="float32")
    valley[8:12, :] = 90.0  # the dam crest: rows 8-11 at 90 m across the valley
    raw = str(tmp_path / "raw_top.tif")
    out = str(tmp_path / "top_carved.tif")
    _write_dem_arr(raw, valley)
    # dam trace along the crest (mid-valley, x spanning the width; y at the crest rows)
    crest_y = _N * _RES - 10.0 * _RES  # row ~10
    dam = LineString([(20.0, crest_y), (180.0, crest_y)])

    n_carved, floor = carve_dam_into_top_dem(
        dem_in_path=raw, dem_out_path=out, dam_lines=[dam], buffer_m=12.0
    )

    assert floor == 55.0  # valley floor found in the neighborhood
    assert n_carved > 0
    with rasterio.open(out) as src:
        carved = src.read(1)
        r, c = rowcol(src.transform, 100.0, crest_y)
    assert carved[r, c] == 55.0  # the crest cell on the dam trace is now the valley floor
    # a cell far from the dam is untouched
    assert carved[0, 0] == 55.0


def test_dam_top_carve_raises_when_no_line(tmp_path) -> None:
    import pytest
    from shapely.geometry import LineString

    raw = str(tmp_path / "raw.tif")
    _write_dem(raw)
    with pytest.raises(ValueError, match="no dam line"):
        carve_dam_into_top_dem(
            dem_in_path=raw,
            dem_out_path=str(tmp_path / "o.tif"),
            dam_lines=[LineString()],
            buffer_m=10.0,
        )
