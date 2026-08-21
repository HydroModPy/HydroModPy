"""Measure how far the computed D8 paths stray from the mapped stream network."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from hydromodpy.spatial.geographic.core.stream_dem_agreement import (
    measure_network_dem_agreement,
)

_N = 20
_RES = 10.0
_TRANSFORM = from_origin(0.0, _N * _RES, _RES, _RES)  # top-left (0, 200), 10 m cells
# Down the middle of column 10, from the north edge to the south edge.
_STREAM = LineString([(105.0, 195.0), (105.0, 5.0)])


def _write_d8(path: str, code: int) -> None:
    profile = {
        "driver": "GTiff",
        "height": _N,
        "width": _N,
        "count": 1,
        "dtype": "int16",
        "crs": "EPSG:2154",
        "transform": _TRANSFORM,
        "nodata": -32768,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full((_N, _N), code, dtype="int16"), 1)


def _write_catchment(path: str) -> None:
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(0.0, 0.0, _N * _RES, _N * _RES)],
        crs="EPSG:2154",
    ).to_file(path)


def _agreement(tmp_path, *, code: int, stream_lines=None):
    d8 = str(tmp_path / "direc.tif")
    catchment = str(tmp_path / "watershed.shp")
    _write_d8(d8, code)
    _write_catchment(catchment)
    return measure_network_dem_agreement(
        d8_pointer_path=d8,
        watershed_shp=catchment,
        stream_lines=[_STREAM] if stream_lines is None else stream_lines,
    )


def test_agreement_is_one_when_the_paths_never_leave_the_network(tmp_path) -> None:
    # Everything flows due south (code 4), so the closure of a north-south trace
    # down column 10 is that column and nothing more.
    agreement = _agreement(tmp_path, code=4)

    assert agreement.n_network_cells == _N
    assert agreement.n_closure_cells == _N
    assert agreement.alpha == pytest.approx(1.0)
    assert agreement.burned is False


def test_agreement_falls_when_the_paths_leave_the_network(tmp_path) -> None:
    # Everything flows south-east (code 2): a trace down column 10 walks off it at
    # the first step, so the closure is a staircase far larger than the trace.
    agreement = _agreement(tmp_path, code=2)

    assert agreement.n_network_cells == _N
    assert agreement.n_closure_cells > _N
    assert agreement.alpha < 1.0


def test_a_network_outside_the_catchment_raises(tmp_path) -> None:
    far_away = [LineString([(50_000.0, 50_000.0), (50_100.0, 50_100.0)])]

    with pytest.raises(ValueError, match="do not share a single cell"):
        _agreement(tmp_path, code=4, stream_lines=far_away)


def test_no_geometry_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="no stream geometry"):
        _agreement(tmp_path, code=4, stream_lines=[])
