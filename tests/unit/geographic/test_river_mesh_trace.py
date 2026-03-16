from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiLineString, box

from hydromodpy.geographic.core.river_mesh_trace import (
    RiverMeshTrace,
    build_river_mesh_trace_from_vector,
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
