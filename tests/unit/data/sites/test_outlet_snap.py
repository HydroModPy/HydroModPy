"""The outlet snap of ``hmp site import``: nearest line, or a refusal."""

from __future__ import annotations

import geopandas as gpd
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Point

from hydromodpy.data.sites.outlet_snap import load_network, snap_outlet

pytestmark = pytest.mark.fast

RIVER = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (100.0, 0.0)])], crs="EPSG:2154")
NO_LINE = gpd.GeoDataFrame(geometry=[Point(0.0, 0.0)], crs="EPSG:2154")


def _snap(y, network, distance):
    return snap_outlet(
        "station_A", (25.0, y), network, crs="EPSG:2154", max_distance_m=distance, source="bdtopage"
    )


def test_an_outlet_is_projected_on_the_nearest_line():
    assert _snap(12.0, RIVER.set_crs(None, allow_override=True), 50.0) == (25.0, 0.0)


@pytest.mark.parametrize(
    ("network", "distance", "match"),
    [
        (RIVER, 50.0, "above the configured limit"),
        (RIVER, 0.0, "max_distance_m must be > 0"),
        (NO_LINE, 50.0, "contains no line geometry"),
        (None, 50.0, "River network is missing"),
    ],
)
def test_a_snap_that_cannot_be_trusted_is_refused(network, distance, match):
    with pytest.raises(ValueError, match=match):
        _snap(120.0, network, distance)


def test_bd_topage_is_fetched_around_the_outlets_then_read_from_the_folder(tmp_path):
    asked = []

    def fetcher(bbox_wgs84, page_size):
        asked.append((page_size, bbox_wgs84))
        return RIVER.to_crs("EPSG:4326")

    for _ in range(2):
        network = load_network(
            source="bdtopage",
            outlets=[(350000.0, 6810000.0)],
            target_crs="EPSG:2154",
            output_dir=tmp_path,
            page_size=50,
            fetcher=fetcher,
        )

    ((page_size, (lon_min, lat_min, lon_max, lat_max)),) = asked
    assert page_size == 50
    lon, lat = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True).transform(
        350000.0, 6810000.0
    )
    assert lon_min < lon < lon_max and lat_min < lat < lat_max
    assert (tmp_path / "bdtopage_reference_network.gpkg").is_file()
    assert str(network.crs) == "EPSG:2154" and len(network) == 1


@pytest.mark.parametrize(
    ("source", "kwargs", "match"),
    [
        ("custom", {}, "needs a path"),
        ("osm", {}, "Unsupported river network source"),
        ("bdtopage", {"outlets": []}, "without outlets"),
        ("bdtopage", {"fetcher": lambda bbox, page_size: RIVER.iloc[:0]}, "returned no feature"),
    ],
)
def test_a_network_that_cannot_be_loaded_is_refused(tmp_path, source, kwargs, match):
    arguments = {
        "outlets": [(25.0, 12.0)],
        "target_crs": "EPSG:2154",
        "output_dir": tmp_path,
        "fetcher": None,
    }
    with pytest.raises(ValueError, match=match):
        load_network(source=source, **(arguments | kwargs))
