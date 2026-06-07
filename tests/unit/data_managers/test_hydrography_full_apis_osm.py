"""OSM Overpass API tests for the hydrography variable manager (mocked HTTP).

Covers Overpass query construction, feature parsing, empty response,
custom waterway types, and the intermittent flag.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

# =====================================================================
# 7. OSM API (mocked HTTP)
# =====================================================================


@pytest.mark.fast
class TestOsmApi:
    BBOX = (-2.5, 47.5, -2.0, 48.0)

    def _overpass_response(self, n=5, waterway="river"):
        elements = []
        for i in range(n):
            elements.append(
                {
                    "type": "way",
                    "id": 1000 + i,
                    "tags": {"waterway": waterway},
                    "geometry": [
                        {"lat": 47.6 + i * 0.01, "lon": -2.3},
                        {"lat": 47.6 + i * 0.01, "lon": -2.2},
                    ],
                }
            )
        return {"elements": elements}

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_parses_features(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        resp = MagicMock()
        resp.text = json.dumps(self._overpass_response(5, "river"))
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="osm")
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 5
        assert str(gdf.crs) == "EPSG:4326"
        assert "waterway" in gdf.columns
        assert "intermit" in gdf.columns

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_empty_response(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        resp = MagicMock()
        resp.text = json.dumps({"elements": []})
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="osm")
        gdf = fetch(cfg, self.BBOX)
        assert gdf.empty

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_custom_waterway_types_in_query(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        resp = MagicMock()
        resp.text = json.dumps(self._overpass_response(2, "canal"))
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="osm", waterway_types=["canal"])
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 2
        # Verify query was built with "canal"
        call_params = mock_get.call_args
        query_data = (
            call_params[1]["params"]["data"] if "params" in call_params[1] else call_params[0][1]
        )
        assert "canal" in str(call_params)

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_intermittent_flag(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.osm import fetch

        elements = [
            {
                "type": "way",
                "id": 1,
                "tags": {"waterway": "stream", "intermittent": "yes"},
                "geometry": [
                    {"lat": 47.6, "lon": -2.3},
                    {"lat": 47.7, "lon": -2.2},
                ],
            },
            {
                "type": "way",
                "id": 2,
                "tags": {"waterway": "stream"},
                "geometry": [
                    {"lat": 47.8, "lon": -2.3},
                    {"lat": 47.9, "lon": -2.2},
                ],
            },
        ]
        resp = MagicMock()
        resp.text = json.dumps({"elements": elements})
        resp.raise_for_status = MagicMock()
        resp.close = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="osm", waterway_types=["stream"])
        gdf = fetch(cfg, self.BBOX)
        assert gdf.iloc[0]["intermit"] == 2  # intermittent
        assert gdf.iloc[1]["intermit"] == 1  # permanent
