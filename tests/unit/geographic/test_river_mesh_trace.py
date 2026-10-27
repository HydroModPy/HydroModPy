"""The river trace a mesh follows, from geometries, from a vector file or from the network."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, box

from hydromodpy.spatial.geographic.core.river_mesh_trace import (
    RiverMeshTrace,
    build_river_mesh_trace_from_vector,
)
from hydromodpy.spatial.geographic.core.river_network import (
    _build_river_mesh_trace_from_network_gdf,
)


def test_river_mesh_trace_from_geometries_computes_metrics():
    trace = RiverMeshTrace.from_geometries(
        source_kind="file",
        crs_wkt="EPSG:2154",
        geometries=[
            LineString([(0.0, 0.0), (1.0, 0.0)]),
            MultiLineString(
                [
                    LineString([(1.0, 0.0), (2.0, 0.0)]),
                    LineString([(2.0, 0.0), (2.0, 1.0)]),
                ]
            ),
        ],
    )

    assert trace.segment_count == 3
    assert trace.total_length_m == pytest.approx(3.0)
    assert len(trace.lines) == 3


def test_build_river_mesh_trace_from_vector_applies_clip_and_target_crs(tmp_path: Path):
    river_path = tmp_path / "river_network.gpkg"
    clip_path = tmp_path / "clip_domain.gpkg"

    rivers = gpd.GeoDataFrame(
        {"id": [1, 2]},
        geometry=[
            LineString([(0.0, 0.0), (0.01, 0.0)]),
            LineString([(1.0, 1.0), (1.01, 1.0)]),
        ],
        crs="EPSG:4326",
    )
    rivers.to_file(river_path, layer="river", driver="GPKG")

    clip = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(-0.1, -0.1, 0.2, 0.2)],
        crs="EPSG:4326",
    )
    clip.to_file(clip_path, layer="clip", driver="GPKG")

    trace = build_river_mesh_trace_from_vector(
        vector_path=river_path,
        source_kind="geographic_generated",
        target_crs="EPSG:3857",
        clip_polygon_path=clip_path,
    )

    assert trace is not None
    assert trace.segment_count == 1
    assert trace.total_length_m > 500.0
    assert "3857" in trace.crs_wkt or "Pseudo-Mercator" in trace.crs_wkt


def test_build_river_mesh_trace_from_vector_missing_file_raises(tmp_path: Path):
    missing = tmp_path / "missing_network.shp"
    with pytest.raises(FileNotFoundError):
        build_river_mesh_trace_from_vector(
            vector_path=missing,
            source_kind="file",
        )


def test_build_river_mesh_trace_from_vector_infers_missing_crs_from_target(
    tmp_path: Path,
):
    river_path = tmp_path / "river_network_no_crs.shp"
    rivers = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(0.0, 0.0), (10.0, 0.0)])],
        crs=None,
    )
    with pytest.warns(UserWarning, match="'crs' was not provided"):
        rivers.to_file(river_path)

    trace = build_river_mesh_trace_from_vector(
        vector_path=river_path,
        source_kind="geographic_generated",
        target_crs="EPSG:2154",
    )

    assert trace is not None
    assert trace.segment_count == 1
    assert "2154" in trace.crs_wkt


def test_build_river_mesh_trace_from_vector_missing_crs_without_target_raises(
    tmp_path: Path,
):
    river_path = tmp_path / "river_network_no_crs.shp"
    rivers = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(0.0, 0.0), (10.0, 0.0)])],
        crs=None,
    )
    with pytest.warns(UserWarning, match="'crs' was not provided"):
        rivers.to_file(river_path)

    with pytest.raises(ValueError, match="has no CRS and no target CRS"):
        build_river_mesh_trace_from_vector(
            vector_path=river_path,
            source_kind="file",
        )


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
    trace = {
        "source_kind": "file",
        "crs_wkt": "EPSG:2154",
        "lines": (LineString([(0, 0), (1, 0)]),),
    }
    trace.update(members)

    with pytest.raises((ValueError, TypeError), match=reason):
        RiverMeshTrace(**trace)


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

    trace = _build_river_mesh_trace_from_network_gdf(network_gdf=network, network_crs=None)

    assert trace.source_kind == "geographic_generated"
    assert trace.segment_count == 2
    assert trace.total_length_m == pytest.approx(150.0)
    assert "2154" in trace.crs_wkt or "Lambert-93" in trace.crs_wkt


def test_a_network_without_crs_takes_the_one_it_is_given():
    network = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (10.0, 0.0)])], crs=None)

    trace = _build_river_mesh_trace_from_network_gdf(network_gdf=network, network_crs="EPSG:2154")

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

    assert (
        _build_river_mesh_trace_from_network_gdf(network_gdf=network, network_crs=network_crs)
        is None
    )
