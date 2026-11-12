"""The river network Whitebox writes is read back as lines (m) and summarised.

The summary gives the stream pixel count, the network length (m), the drainage
density (km per km2) and the highest Strahler order of a small watershed.
"""

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString, MultiLineString, box

from hydromodpy.catchment.algorithms.river_network_config import RiverNetworkConfig
from hydromodpy.catchment.algorithms.river_network_vector import (
    build_network_gdf_from_whitebox_vector,
    compute_river_network_summary,
    remove_vector_sidecars,
)
from tests._helpers.geographic_cases import write_features
from tests._helpers.geotiffs import write_geotiff


def _record(points: list[tuple[float, float]], parts: list[int]) -> SimpleNamespace:
    return SimpleNamespace(points=[SimpleNamespace(x=x, y=y) for x, y in points], parts=parts)


def _vector(*records: SimpleNamespace, projection: str = "") -> SimpleNamespace:
    return SimpleNamespace(records=list(records), projection=projection)


FOUR = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)]

RECORDS = [
    pytest.param(_record(FOUR, [0]), LineString(FOUR), id="one part"),
    pytest.param(
        _record(FOUR, [0, 2]),
        MultiLineString([FOUR[:2], FOUR[2:]]),
        id="two parts",
    ),
    pytest.param(_record(FOUR[:3], [0, 2]), LineString(FOUR[:2]), id="part of one point dropped"),
    pytest.param(_record(FOUR[:2], []), LineString(FOUR[:2]), id="no part index"),
]


@pytest.mark.parametrize(("record", "expected"), RECORDS)
def test_lines_of_a_whitebox_record(record, expected) -> None:
    network = build_network_gdf_from_whitebox_vector(
        vector_obj=_vector(record, _record(FOUR[:1], [0])), network_crs="EPSG:2154"
    )

    assert len(network) == 1
    assert network.geometry.iloc[0].equals(expected)
    assert network.crs.to_epsg() == 2154


def test_record_of_single_points_gives_no_line() -> None:
    # Three vertices, each its own part: no part has two points.
    network = build_network_gdf_from_whitebox_vector(
        vector_obj=_vector(_record(FOUR[:3], [0, 1, 2])), network_crs="EPSG:2154"
    )

    assert network.empty


def test_crs_of_the_vector_wins() -> None:
    network = build_network_gdf_from_whitebox_vector(
        vector_obj=_vector(_record(FOUR, [0]), projection="EPSG:4326"), network_crs="EPSG:2154"
    )

    assert network.crs.to_epsg() == 4326


def test_vector_without_crs_or_line() -> None:
    network = build_network_gdf_from_whitebox_vector(vector_obj=_vector(), network_crs=None)

    assert network.empty
    assert network.crs is None


def test_sidecars_removed(tmp_path) -> None:
    shapefile = tmp_path / "network.shp"
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        shapefile.with_suffix(suffix).write_text("x")
    other = tmp_path / "network.gpkg"
    other.write_text("x")
    kept = tmp_path / "notes.txt"
    kept.write_text("x")

    remove_vector_sidecars(shapefile)
    remove_vector_sidecars(other)
    remove_vector_sidecars(tmp_path / "gone.gpkg")

    assert [p.name for p in tmp_path.iterdir()] == ["notes.txt"]


def _watershed(tmp_path):
    return write_features(tmp_path / "watershed.shp", [box(0.0, 0.0, 1000.0, 2000.0)])  # 2 km2


def test_summary_of_a_network(tmp_path) -> None:
    streams = write_geotiff(tmp_path / "streams.tif", np.array([[1, 0], [1, 1]]), nodata=-9999.0)
    order = write_geotiff(tmp_path / "order.tif", np.array([[2, 0], [1, 3]]), nodata=-9999.0)
    network = build_network_gdf_from_whitebox_vector(
        vector_obj=_vector(_record([(0.0, 0.0), (0.0, 3000.0)], [0])), network_crs="EPSG:2154"
    )

    summary = compute_river_network_summary(
        river_network=RiverNetworkConfig(threshold_area_km2=0.5, enabled=True),
        threshold_cells=800.0,
        active_streams_tif=streams,
        watershed_shp=_watershed(tmp_path),
        stream_order_strahler_tif=order,
        network_gdf=network,
    )

    assert summary["stream_pixel_count"] == 3
    assert summary["segment_count"] == 1
    assert summary["network_total_length_m"] == pytest.approx(3000.0)
    assert summary["catchment_area_km2"] == pytest.approx(2.0)
    assert summary["drainage_density_km_per_km2"] == pytest.approx(1.5)  # 3 km / 2 km2
    assert summary["max_strahler_order"] == 3.0
    assert (summary["threshold_mode"], summary["threshold_value"]) == ("area_km2", 0.5)


def test_summary_without_network_or_order(tmp_path) -> None:
    streams = write_geotiff(tmp_path / "streams.tif", np.zeros((2, 2)), nodata=-9999.0)
    order = write_geotiff(tmp_path / "order.tif", np.zeros((2, 2)), nodata=-9999.0)

    summary = compute_river_network_summary(
        river_network=RiverNetworkConfig(threshold_mode="cells", threshold_cells=50.0),
        threshold_cells=50.0,
        active_streams_tif=streams,
        watershed_shp=_watershed(tmp_path),
        stream_order_strahler_tif=order,
    )

    assert (summary["stream_pixel_count"], summary["segment_count"]) == (0, 0)
    assert summary["network_total_length_m"] == 0.0
    assert summary["drainage_density_km_per_km2"] == 0.0
    assert summary["max_strahler_order"] is None
    assert (summary["threshold_mode"], summary["threshold_value"]) == ("cells", 50.0)
