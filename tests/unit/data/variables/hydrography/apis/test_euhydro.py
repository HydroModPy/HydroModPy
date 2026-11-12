"""EU-Hydro river layers from an ArcGIS MapServer, asked over a degree box.

The map server lists layers in a group. Each Strahler layer is queried and the
features are stacked with the layer id and name.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.core.io.fetch import HTTPClient
from hydromodpy.data.variables.hydrography.apis.euhydro import (
    _feature_layer_ids_in_group,
    fetch,
)
from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

pytestmark = pytest.mark.fast

BBOX = (10.0, 45.0, 11.0, 46.0)  # degrees


def mapserver_json(group_name="River_Net_lines", layer_ids=(5, 6)):
    group = {"id": 0, "name": group_name, "type": "Group Layer", "parentLayerId": -1}
    layers = [
        {"id": i, "name": f"Strahler_{i}", "type": "Feature Layer", "parentLayerId": 0}
        for i in layer_ids
    ]
    return {"layers": [group, *layers]}


def layer_query_json(n=3):
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[10.0 + i * 0.01, 45.5], [10.1 + i * 0.01, 45.6]],
            },
            "properties": {"OBJECTID": i, "STRAHLER": 3},
        }
        for i in range(n)
    ]
    return {"type": "FeatureCollection", "features": features}


def reply(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


@patch("hydromodpy.core.io.fetch.HTTPClient.get")
def test_two_layers_are_stacked(mock_get):
    mock_get.side_effect = [
        reply(mapserver_json(layer_ids=(5, 6))),
        reply({"name": "Strahler_5"}),
        reply({"name": "Strahler_6"}),
        reply(layer_query_json(2)),
        reply(layer_query_json(1)),
    ]

    gdf = fetch(HydrographySourceConfig(source="euhydro"), BBOX, client=HTTPClient())

    assert len(gdf) == 3  # 2 + 1
    assert "layer_id" in gdf.columns
    assert "layer_name" in gdf.columns


@patch("hydromodpy.core.io.fetch.HTTPClient.get")
def test_no_layer_found(mock_get):
    mock_get.return_value = reply({"layers": []})

    gdf = fetch(HydrographySourceConfig(source="euhydro"), BBOX, client=HTTPClient())

    assert gdf.empty


def test_strahler_fallback():
    # The group name does not match, so the layers named Strahler are taken.
    ms = {
        "layers": [
            {"id": 0, "name": "Other_Group", "type": "Group Layer", "parentLayerId": -1},
            {"id": 10, "name": "Strahler_Order_3", "type": "Feature Layer", "parentLayerId": 99},
        ]
    }

    assert 10 in _feature_layer_ids_in_group(ms, "River_Net_lines")


@patch("hydromodpy.core.io.fetch.HTTPClient.get")
def test_custom_group_and_page_size(mock_get):
    mock_get.side_effect = [
        reply(mapserver_json(group_name="Canal_lines", layer_ids=(7,))),
        reply({"name": "Canal_7"}),
        reply(layer_query_json(1)),
    ]
    cfg = HydrographySourceConfig(source="euhydro", group_name="Canal_lines", euhydro_page_size=50)

    gdf = fetch(cfg, BBOX, client=HTTPClient())

    assert len(gdf) == 1
