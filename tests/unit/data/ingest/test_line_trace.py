"""Readers of a line trace (a dam or a barrier) from a CSV of x, y or a vector file, as one polyline."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from hydromodpy.data.ingest.line_trace import _read_barrier_csv, read_line_trace


def test_read_barrier_csv_accepts_lon_lat_headers(tmp_path) -> None:
    path = tmp_path / "dam.csv"
    path.write_text("lon,lat\n0,0\n10,10\n", encoding="utf-8")
    assert list(_read_barrier_csv(path, "test").coords) == [(0.0, 0.0), (10.0, 10.0)]


def test_read_barrier_csv_refuses_fewer_than_two_rows(tmp_path) -> None:
    path = tmp_path / "single.csv"
    path.write_text("x,y\n0,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="needs at least two"):
        _read_barrier_csv(path, "test")


def test_read_line_trace_dispatches_csv(tmp_path) -> None:
    path = tmp_path / "trace.csv"
    path.write_text("x,y\n100,200\n300,400\n", encoding="utf-8")
    line = read_line_trace(path, where="test")
    assert isinstance(line, LineString)
    assert list(line.coords) == [(100.0, 200.0), (300.0, 400.0)]


def test_read_line_trace_stitches_contiguous_multilinestring(tmp_path) -> None:
    path = tmp_path / "multi.geojson"
    multi = MultiLineString([([(0, 0), (5, 5)]), ([(5, 5), (10, 10)])])
    gpd.GeoDataFrame(geometry=[multi], crs="EPSG:2154").to_file(path, driver="GeoJSON")
    line = read_line_trace(path, where="test")
    assert line.geom_type == "LineString"
    assert list(line.coords) == [(0.0, 0.0), (5.0, 5.0), (10.0, 10.0)]


def test_read_line_trace_reprojects_to_project_crs(tmp_path) -> None:
    path = tmp_path / "wgs84.geojson"
    gpd.GeoDataFrame(geometry=[LineString([(-1.5, 48.0), (-1.4, 48.1)])], crs="EPSG:4326").to_file(
        path, driver="GeoJSON"
    )
    line = read_line_trace(path, where="test", project_crs="EPSG:2154")
    assert line.geom_type == "LineString"
    # EPSG:2154 coords in Brittany are in hundreds of km
    assert line.coords[0][0] > 100000.0


def test_read_line_trace_refuses_empty_geometry(tmp_path) -> None:
    path = tmp_path / "empty.geojson"
    gpd.GeoDataFrame(geometry=[], crs="EPSG:2154").to_file(path, driver="GeoJSON")
    with pytest.raises(ValueError, match="has no geometry"):
        read_line_trace(path, where="test")


def test_read_line_trace_refuses_non_line_geometry(tmp_path) -> None:
    path = tmp_path / "poly.geojson"
    gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])], crs="EPSG:2154"
    ).to_file(path, driver="GeoJSON")
    with pytest.raises(ValueError, match="provide one contiguous polyline"):
        read_line_trace(path, where="test")
