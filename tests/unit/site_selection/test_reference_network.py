from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.candidates.reference_network import (
    snap_outlet_to_reference_network,
)


@pytest.mark.fast
def test_snap_outlet_to_reference_network_projects_to_nearest_line():
    network = gpd.GeoDataFrame(
        geometry=[LineString([(0.0, 0.0), (100.0, 0.0)])],
        crs="EPSG:2154",
    )
    outlet = CandidateOutlet(
        candidate_id="station_A",
        x=25.0,
        y=12.0,
        crs="EPSG:2154",
        source="station_outlets",
    )

    snapped = snap_outlet_to_reference_network(
        outlet,
        network,
        max_distance_m=50.0,
        source="bdtopage",
    )

    assert snapped.x == pytest.approx(25.0)
    assert snapped.y == pytest.approx(0.0)
    assert snapped.attributes["reference_network_source"] == "bdtopage"
    assert snapped.attributes["reference_network_snap_distance_m"] == pytest.approx(12.0)
    assert snapped.attributes["station_x"] == pytest.approx(25.0)
    assert snapped.attributes["station_y"] == pytest.approx(12.0)


@pytest.mark.fast
def test_snap_outlet_to_reference_network_rejects_distant_station():
    network = gpd.GeoDataFrame(
        geometry=[LineString([(0.0, 0.0), (100.0, 0.0)])],
        crs="EPSG:2154",
    )
    outlet = CandidateOutlet(
        candidate_id="station_A",
        x=25.0,
        y=120.0,
        crs="EPSG:2154",
        source="station_outlets",
    )

    with pytest.raises(ValueError, match="above the configured limit"):
        snap_outlet_to_reference_network(
            outlet,
            network,
            max_distance_m=50.0,
            source="bdtopage",
        )
