"""The river trace a mesh follows, from geometries, from a vector file or from the network."""

from contextlib import nullcontext
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, box

from hydromodpy.spatial.geographic.core.river_mesh_trace import (
    RiverMeshTrace,
    build_river_mesh_trace_from_network_gdf,
    build_river_mesh_trace_from_vector,
)
from tests._helpers.geographic_cases import write_features


def test_river_mesh_trace_from_geometries_computes_metrics():
    lines = [LineString([(0, 0), (1, 0)]), MultiLineString([[(1, 0), (2, 0)], [(2, 0), (2, 1)]])]
    trace = RiverMeshTrace.from_geometries(
        source_kind="file", crs_wkt="EPSG:2154", geometries=lines
    )
    assert (trace.segment_count, len(trace.lines)) == (3, 3)
    assert trace.total_length_m == pytest.approx(3.0)


def test_build_river_mesh_trace_from_vector_applies_clip_and_target_crs(tmp_path: Path):
    rivers = write_features(
        tmp_path / "river_network.gpkg",
        [LineString([(0.0, 0.0), (0.01, 0.0)]), LineString([(1.0, 1.0), (1.01, 1.0)])],
        crs="EPSG:4326",
    )
    clip = write_features(tmp_path / "clip.gpkg", [box(-0.1, -0.1, 0.2, 0.2)], crs="EPSG:4326")
    trace = build_river_mesh_trace_from_vector(
        vector_path=rivers,
        source_kind="geographic_generated",
        target_crs="EPSG:3857",
        clip_polygon_path=clip,
    )
    assert trace.segment_count == 1
    assert trace.total_length_m > 500.0
    assert "3857" in trace.crs_wkt or "Pseudo-Mercator" in trace.crs_wkt
    assert trace.as_multilinestring().length == pytest.approx(trace.total_length_m)


@pytest.mark.filterwarnings("ignore:'crs' was not provided")
@pytest.mark.parametrize(
    ("target", "clip_crs", "crs"),
    [("EPSG:2154", None, "2154"), (None, "EPSG:2154", "Lambert"), ("  ", "EPSG:2154", "Lambert")],
    ids=["from the target", "from the clip", "blank target, from the clip"],
)
def test_a_vector_without_crs_takes_the_target_or_the_clip_crs(tmp_path, target, clip_crs, crs):
    rivers = write_features(tmp_path / "rivers.shp", [LineString([(0, 0), (10, 0)])], crs=None)
    clip = None
    if clip_crs is not None:
        clip = write_features(tmp_path / "clip.shp", [box(-5, -5, 5, 5)], crs=clip_crs)
    trace = build_river_mesh_trace_from_vector(
        vector_path=rivers, source_kind="file", target_crs=target, clip_polygon_path=clip
    )
    assert crs in trace.crs_wkt
    assert trace.total_length_m == pytest.approx(10.0 if clip is None else 5.0)


def _rivers(tmp_path, geometries=None, crs="EPSG:2154"):
    lines = [LineString([(0, 0), (10, 0)])] if geometries is None else geometries
    return write_features(tmp_path / "rivers.shp", lines, crs=crs)


def _clip(tmp_path, geometries, crs="EPSG:2154"):
    return write_features(tmp_path / "clip.shp", geometries, crs=crs)


# fmt: off
NO_TRACE = {
    "missing vector": (lambda t: t / "missing.shp", lambda t: None, FileNotFoundError, None),
    "no crs anywhere": (lambda t: _rivers(t, crs=None), lambda t: None, ValueError, "has no CRS and no target CRS"),
    "missing clip": (_rivers, lambda t: t / "gone.shp", FileNotFoundError, None),
    "clip without crs": (_rivers, lambda t: _clip(t, [box(0, 0, 1, 1)], crs=None), ValueError, "Clip polygon has no CRS"),
    "empty vector": (lambda t: _rivers(t, []), lambda t: None, None, None),
    "empty clip": (_rivers, lambda t: _clip(t, []), None, None),
    "clip away from the lines": (_rivers, lambda t: _clip(t, [box(50, 50, 60, 60)]), None, None),
    "no line in the vector": (lambda t: _rivers(t, [Point(0, 0).buffer(1)]), lambda t: None, None, None),
}
# fmt: on


@pytest.mark.filterwarnings("ignore:'crs' was not provided")
@pytest.mark.parametrize(
    ("vector", "clip", "error", "match"), NO_TRACE.values(), ids=list(NO_TRACE)
)
def test_a_vector_that_gives_no_line_gives_no_trace_or_says_why(
    tmp_path, vector, clip, error, match
):
    with nullcontext() if error is None else pytest.raises(error, match=match):
        trace = build_river_mesh_trace_from_vector(
            vector_path=vector(tmp_path), source_kind="file", clip_polygon_path=clip(tmp_path)
        )
        assert trace is None


def test_a_clip_that_cuts_a_line_in_two_keeps_both_parts(tmp_path):
    rivers = _rivers(tmp_path, [LineString([(0, 0), (10, 0), (10, 10), (0, 10)])])
    corner = _clip(tmp_path, [box(-1, -1, 5, 11)])
    trace = build_river_mesh_trace_from_vector(
        vector_path=rivers, source_kind="file", clip_polygon_path=corner
    )
    assert trace.segment_count == 2
    assert trace.total_length_m == pytest.approx(10.0)


@pytest.mark.parametrize(
    ("members", "reason"),
    [
        ({"source_kind": "drawn"}, "source_kind must be one of"),
        ({"crs_wkt": "  "}, "crs_wkt cannot be empty"),
        ({"lines": (LineString(),)}, "lines cannot be empty"),
        ({"lines": (Point(0.0, 0.0),)}, "only LineString or MultiLineString"),
    ],
)
def test_a_trace_refuses_what_a_mesh_cannot_follow(members: dict, reason: str):
    trace = dict(source_kind="file", crs_wkt="EPSG:2154", lines=(LineString([(0, 0), (1, 0)]),))
    with pytest.raises((ValueError, TypeError), match=reason):
        RiverMeshTrace(**{**trace, **members})


def test_the_network_gives_its_lines_and_drops_what_is_not_a_line():
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


def test_a_network_without_crs_takes_the_one_it_is_given():
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
def test_a_network_that_gives_no_line_gives_no_trace(geometry, network_crs, crs):
    geometries = [] if geometry is None else [geometry]
    network = gpd.GeoDataFrame(geometry=geometries, crs=crs)
    trace = build_river_mesh_trace_from_network_gdf(network_gdf=network, network_crs=network_crs)
    assert trace is None
