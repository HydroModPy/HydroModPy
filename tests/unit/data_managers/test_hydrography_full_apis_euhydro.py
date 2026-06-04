"""EU-Hydro MapServer API tests for the hydrography variable manager (mocked HTTP).

Covers MapServer layer discovery, multi-layer query, the Strahler group
fallback, no-layers guard, and custom group/page-size.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

# =====================================================================
# 9. EU-Hydro API (mocked HTTP)
# =====================================================================


@pytest.mark.fast
class TestEuHydroApi:
    BBOX = (10.0, 45.0, 11.0, 46.0)

    def _mapserver_json(self, group_name="River_Net_lines", layer_ids=(5, 6)):
        layers = [
            {"id": 0, "name": group_name, "type": "Group Layer", "parentLayerId": -1},
        ]
        for lid in layer_ids:
            layers.append(
                {
                    "id": lid,
                    "name": f"Strahler_{lid}",
                    "type": "Feature Layer",
                    "parentLayerId": 0,
                }
            )
        return {"layers": layers}

    def _layer_query_json(self, n=3):
        features = []
        for i in range(n):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[10.0 + i * 0.01, 45.5], [10.1 + i * 0.01, 45.6]],
                    },
                    "properties": {"OBJECTID": i, "STRAHLER": 3},
                }
            )
        return {"type": "FeatureCollection", "features": features}

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_two_layers(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

        ms_resp = MagicMock()
        ms_resp.json.return_value = self._mapserver_json(layer_ids=(5, 6))
        ms_resp.raise_for_status = MagicMock()

        name5_resp = MagicMock()
        name5_resp.json.return_value = {"name": "Strahler_5"}
        name5_resp.raise_for_status = MagicMock()

        name6_resp = MagicMock()
        name6_resp.json.return_value = {"name": "Strahler_6"}
        name6_resp.raise_for_status = MagicMock()

        data5_resp = MagicMock()
        data5_resp.json.return_value = self._layer_query_json(2)
        data5_resp.raise_for_status = MagicMock()

        data6_resp = MagicMock()
        data6_resp.json.return_value = self._layer_query_json(1)
        data6_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [ms_resp, name5_resp, name6_resp, data5_resp, data6_resp]

        cfg = HydrographySourceConfig(source="euhydro")
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 3  # 2 + 1
        assert "layer_id" in gdf.columns
        assert "layer_name" in gdf.columns

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_no_layers_found(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

        ms_resp = MagicMock()
        ms_resp.json.return_value = {"layers": []}
        ms_resp.raise_for_status = MagicMock()
        mock_get.return_value = ms_resp

        cfg = HydrographySourceConfig(source="euhydro")
        gdf = fetch(cfg, self.BBOX)
        assert gdf.empty

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_strahler_fallback(self, mock_get):
        """When group_name doesn't match, fallback finds layers with 'Strahler' in name."""
        from hydromodpy.data.variables.hydrography.apis.euhydro import (
            _feature_layer_ids_in_group,
        )

        ms = {
            "layers": [
                {"id": 0, "name": "Other_Group", "type": "Group Layer", "parentLayerId": -1},
                {
                    "id": 10,
                    "name": "Strahler_Order_3",
                    "type": "Feature Layer",
                    "parentLayerId": 99,
                },
            ]
        }
        ids = _feature_layer_ids_in_group(ms, "River_Net_lines")
        assert 10 in ids

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_custom_group_and_page_size(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

        ms_resp = MagicMock()
        ms_resp.json.return_value = self._mapserver_json(group_name="Canal_lines", layer_ids=(7,))
        ms_resp.raise_for_status = MagicMock()

        name7_resp = MagicMock()
        name7_resp.json.return_value = {"name": "Canal_7"}
        name7_resp.raise_for_status = MagicMock()

        data7_resp = MagicMock()
        data7_resp.json.return_value = self._layer_query_json(1)
        data7_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [ms_resp, name7_resp, data7_resp]

        cfg = HydrographySourceConfig(
            source="euhydro", group_name="Canal_lines", euhydro_page_size=50
        )
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 1
