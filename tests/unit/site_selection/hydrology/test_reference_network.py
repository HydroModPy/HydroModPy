from __future__ import annotations

import geopandas as gpd
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Point

from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.hydrology.reference_network import (
    load_reference_network_for_outlets,
    score_outlets_against_reference_network,
    snap_outlet_to_reference_network,
)

pytestmark = pytest.mark.fast

RIVER = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (100.0, 0.0)])], crs="EPSG:2154")
NO_LINE = gpd.GeoDataFrame(geometry=[Point(0.0, 0.0)], crs="EPSG:2154")


def _outlet(y: float = 12.0) -> CandidateOutlet:
    return CandidateOutlet("station_A", 25.0, y, "EPSG:2154", "station_outlets")


def test_an_outlet_is_projected_on_the_nearest_line():
    snapped = snap_outlet_to_reference_network(
        _outlet(), RIVER.set_crs(None, allow_override=True), max_distance_m=50.0, source="bdtopage"
    )

    assert (snapped.x, snapped.y) == (25.0, 0.0)
    assert snapped.attributes["reference_network_snap_distance_m"] == 12.0
    assert snapped.attributes["reference_network_source"] == "bdtopage"
    assert (snapped.attributes["station_x"], snapped.attributes["station_y"]) == (25.0, 12.0)


@pytest.mark.parametrize(
    ("network", "distance", "match"),
    [
        (RIVER, 50.0, "above the configured limit"),
        (RIVER, 0.0, "max_distance_m must be > 0"),
        (NO_LINE, 50.0, "contains no line geometry"),
        (None, 50.0, "Reference network is missing"),
    ],
)
def test_a_snap_that_cannot_be_trusted_is_refused(network, distance, match):
    with pytest.raises(ValueError, match=match):
        snap_outlet_to_reference_network(
            _outlet(120.0), network, max_distance_m=distance, source="bdtopage"
        )


def test_the_score_falls_with_the_distance_and_is_null_without_a_line():
    near, far = score_outlets_against_reference_network(
        [_outlet(), _outlet(150.0)], RIVER.to_crs("EPSG:4326"), max_distance_m=100.0, source="x"
    )
    (alone,) = score_outlets_against_reference_network(
        [_outlet()], RIVER.iloc[:0], max_distance_m=100.0, source="x"
    )

    assert near.attributes["reference_network_score"] == pytest.approx(0.88)
    assert far.attributes["reference_network_status"] == "far_from_reference_network"
    assert far.attributes["reference_network_score"] == 0.0
    assert alone.attributes["reference_network_status"] == "empty_reference_network"
    with pytest.raises(ValueError, match="max_distance_m must be > 0"):
        score_outlets_against_reference_network([_outlet()], RIVER, max_distance_m=0.0, source="x")


def test_bd_topage_is_fetched_around_the_outlets_then_read_from_the_run(tmp_path):
    asked = []

    def fetcher(cfg, bbox_wgs84):
        asked.append((cfg.page_size, bbox_wgs84))
        return RIVER.to_crs("EPSG:4326")

    for _ in range(2):
        network, bundle = load_reference_network_for_outlets(
            source="bdtopage",
            outlets=[CandidateOutlet("a", 350000.0, 6810000.0, "EPSG:2154", "s")],
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
    assert bundle.to_manifest_record()["path"] == str(tmp_path / "bdtopage_reference_network.gpkg")
    assert str(network.crs) == "EPSG:2154" and bundle.feature_count == 1


@pytest.mark.parametrize(
    ("source", "kwargs", "match"),
    [
        ("custom", {}, "reference_network_path is required"),
        ("osm", {}, "Unsupported reference network source"),
        ("bdtopage", {"outlets": []}, "without outlets"),
        ("bdtopage", {"fetcher": lambda cfg, bbox: RIVER.iloc[:0]}, "returned no feature"),
    ],
)
def test_a_reference_network_that_cannot_be_loaded_is_refused(tmp_path, source, kwargs, match):
    arguments = {"outlets": [_outlet()], "target_crs": "EPSG:2154", "output_dir": tmp_path}

    with pytest.raises(ValueError, match=match):
        load_reference_network_for_outlets(source=source, **(arguments | kwargs))
