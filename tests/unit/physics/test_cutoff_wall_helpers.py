"""Cutoff-wall trace helpers: auto placement, CSV reading, single-line files."""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.physics.flow.structure_binders import (
    _read_barrier_csv,
    _resolve_barrier_line,
    auto_dam_axis,
)


def test_auto_dam_axis_is_perpendicular_to_the_outlet_flow() -> None:
    # Outlet due north of a tall reservoir: the dam axis runs east-west (constant y)
    # at the downstream edge, spanning the reservoir width.
    reservoir = Polygon([(0, 0), (10, 0), (10, 40), (0, 40)])
    axis = auto_dam_axis(reservoir, (5.0, 60.0))
    (x0, y0), (x1, y1) = axis.coords[0], axis.coords[-1]
    assert y0 == pytest.approx(40.0) and y1 == pytest.approx(40.0)
    assert axis.centroid.x == pytest.approx(5.0)
    assert axis.length >= 10.0  # the reservoir width, plus the abutment extension


def test_read_barrier_csv_builds_a_multi_vertex_polyline(tmp_path) -> None:
    path = tmp_path / "dam.csv"
    path.write_text("x,y\n0,0\n5,1\n10,0\n")
    line = _read_barrier_csv(path, "test")
    assert list(line.coords) == [(0.0, 0.0), (5.0, 1.0), (10.0, 0.0)]


def test_read_barrier_csv_accepts_lon_lat_headers(tmp_path) -> None:
    path = tmp_path / "dam.csv"
    path.write_text("lon,lat\n0,0\n10,10\n")
    assert list(_read_barrier_csv(path, "test").coords) == [(0.0, 0.0), (10.0, 10.0)]


def test_resolve_barrier_line_reads_a_single_linestring_file(tmp_path) -> None:
    # A vector file holding one LineString must resolve cleanly: linemerge rejects a
    # lone LineString, so the resolver must not call it on a single-part geometry.
    path = tmp_path / "wall.geojson"
    gpd.GeoDataFrame(geometry=[LineString([(0, 0), (10, 10)])], crs="EPSG:2154").to_file(
        path, driver="GeoJSON"
    )
    cfg = SimpleNamespace(line=None, line_path=str(path))
    line = _resolve_barrier_line(cfg, where="test")
    assert line.geom_type == "LineString"
    assert len(line.coords) == 2
