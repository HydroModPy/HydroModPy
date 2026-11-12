"""OSM waterways from the Overpass API, asked over a degree box.

Each way becomes a line in EPSG:4326 with its waterway tag.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.core.io.fetch import HTTPClient
from hydromodpy.data.variables.hydrography.apis.osm import fetch
from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

pytestmark = pytest.mark.fast

BBOX = (-2.5, 47.5, -2.0, 48.0)  # degrees


def overpass_reply(n=5, waterway="river"):
    elements = [
        {
            "type": "way",
            "id": 1000 + i,
            "tags": {"waterway": waterway},
            "geometry": [
                {"lat": 47.6 + i * 0.01, "lon": -2.3},
                {"lat": 47.6 + i * 0.01, "lon": -2.2},
            ],
        }
        for i in range(n)
    ]
    response = MagicMock()
    response.text = json.dumps({"elements": elements})
    return response


@patch("hydromodpy.core.io.fetch.HTTPClient.get")
def test_ways_become_lines(mock_get):
    mock_get.return_value = overpass_reply(5, "river")

    gdf = fetch(HydrographySourceConfig(source="osm"), BBOX, client=HTTPClient())

    assert len(gdf) == 5
    assert str(gdf.crs) == "EPSG:4326"
    assert "waterway" in gdf.columns
    assert "intermit" in gdf.columns


@patch("hydromodpy.core.io.fetch.HTTPClient.get")
def test_empty_response(mock_get):
    mock_get.return_value = overpass_reply(0)

    gdf = fetch(HydrographySourceConfig(source="osm"), BBOX, client=HTTPClient())

    assert gdf.empty


@patch("hydromodpy.core.io.fetch.HTTPClient.get")
def test_custom_waterway_types_are_in_the_query(mock_get):
    mock_get.return_value = overpass_reply(2, "canal")
    cfg = HydrographySourceConfig(source="osm", waterway_types=["canal"])

    gdf = fetch(cfg, BBOX, client=HTTPClient())

    assert len(gdf) == 2
    assert "canal" in str(mock_get.call_args)
