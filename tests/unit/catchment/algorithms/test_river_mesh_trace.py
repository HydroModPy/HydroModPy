"""The river trace a mesh follows, from geometries or from the network."""

import logging

import geopandas as gpd
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point

from hydromodpy.catchment.algorithms.river_mesh_trace import (
    RiverMeshTrace,
    build_river_mesh_trace_from_network_gdf,
)


def test_trace_metrics():
    lines = [LineString([(0, 0), (1, 0)]), MultiLineString([[(1, 0), (2, 0)], [(2, 0), (2, 1)]])]
    trace = RiverMeshTrace.from_geometries(
        source_kind="file", crs_wkt="EPSG:2154", geometries=lines
    )
    assert (trace.segment_count, len(trace.lines)) == (3, 3)
    assert trace.total_length_m == pytest.approx(3.0)
    merged = trace.as_multilinestring()
    assert len(merged.geoms) == 3
    assert merged.length == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("members", "reason"),
    [
        ({"source_kind": "drawn"}, "source_kind must be one of"),
        ({"crs_wkt": "  "}, "crs_wkt cannot be empty"),
        ({"lines": (LineString(),)}, "lines cannot be empty"),
        ({"lines": (Point(0.0, 0.0),)}, "only LineString or MultiLineString"),
    ],
)
def test_refusals(members: dict, reason: str):
    trace = dict(source_kind="file", crs_wkt="EPSG:2154", lines=(LineString([(0, 0), (1, 0)]),))
    with pytest.raises((ValueError, TypeError), match=reason):
        RiverMeshTrace(**{**trace, **members})


def test_lines_of_a_network():
    network = gpd.GeoDataFrame(
        geometry=[
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            GeometryCollection([Point(5.0, 5.0), LineString([(100.0, 0.0), (100.0, 50.0)])]),
            Point(1.0, 1.0),
            None,
        ],
        crs="EPSG:2154",
    )
    trace = build_river_mesh_trace_from_network_gdf(network_gdf=network, network_crs=None)
    assert trace.source_kind == "geographic_generated"
    assert trace.segment_count == 2
    assert trace.total_length_m == pytest.approx(150.0)
    assert "2154" in trace.crs_wkt or "Lambert-93" in trace.crs_wkt


def test_crs_given_to_a_bare_network():
    network = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (10.0, 0.0)])], crs=None)
    trace = build_river_mesh_trace_from_network_gdf(network_gdf=network, network_crs="EPSG:2154")
    assert "Lambert-93" in trace.crs_wkt


@pytest.mark.parametrize(
    ("geometry", "network_crs", "crs"),
    [
        (None, "EPSG:2154", "EPSG:2154"),
        (LineString([(0.0, 0.0), (10.0, 0.0)]), "  ", None),
        (Point(0.0, 0.0), None, "EPSG:2154"),
    ],
    ids=["empty network", "no crs anywhere", "no line"],
)
def test_no_line_no_trace(geometry, network_crs, crs):
    geometries = [] if geometry is None else [geometry]
    network = gpd.GeoDataFrame(geometry=geometries, crs=crs)
    trace = build_river_mesh_trace_from_network_gdf(network_gdf=network, network_crs=network_crs)
    assert trace is None


def test_no_crs_anywhere_warns(caplog):
    network = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (10.0, 0.0)])], crs=None)
    with caplog.at_level(logging.WARNING):
        trace = build_river_mesh_trace_from_network_gdf(network_gdf=network, network_crs="")
    assert trace is None
    assert "no river trace is built" in caplog.text
