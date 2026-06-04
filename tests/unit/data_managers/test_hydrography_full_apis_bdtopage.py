"""BD Topage WFS API tests for the hydrography variable manager (mocked HTTP).

Covers WFS hits + feature retrieval, empty bbox, pagination, and custom
typename.
"""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

# =====================================================================
# 8. BD Topage API (mocked HTTP)
# =====================================================================


@pytest.mark.fast
class TestBdTopageApi:
    BBOX = (-2.5, 47.5, -2.0, 48.0)

    def _hits_xml(self, n):
        return textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <wfs:FeatureCollection numberMatched="{n}"
              xmlns:wfs="http://www.opengis.net/wfs/2.0"/>
        """).encode()

    def _features_json(self, n):
        features = []
        for i in range(n):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-2.3 + i * 0.01, 47.6], [-2.2 + i * 0.01, 47.7]],
                    },
                    "properties": {"gid": i, "CdOH": f"R{i:04d}"},
                }
            )
        return {"type": "FeatureCollection", "features": features}

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_with_features(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        hits_resp = MagicMock()
        hits_resp.content = self._hits_xml(3)
        hits_resp.raise_for_status = MagicMock()

        data_resp = MagicMock()
        data_resp.json.return_value = self._features_json(3)
        data_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [hits_resp, data_resp]

        cfg = HydrographySourceConfig(source="bdtopage")
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 3
        assert str(gdf.crs) == "EPSG:4326"
        assert "gid" in gdf.columns

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_fetch_zero_hits(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        resp = MagicMock()
        resp.content = self._hits_xml(0)
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        cfg = HydrographySourceConfig(source="bdtopage")
        gdf = fetch(cfg, self.BBOX)
        assert gdf.empty

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_pagination(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        hits_resp = MagicMock()
        hits_resp.content = self._hits_xml(5)
        hits_resp.raise_for_status = MagicMock()

        page1_resp = MagicMock()
        page1_resp.json.return_value = self._features_json(2)
        page1_resp.raise_for_status = MagicMock()

        page2_resp = MagicMock()
        page2_resp.json.return_value = self._features_json(1)  # < page_size → stop
        page2_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [hits_resp, page1_resp, page2_resp]

        cfg = HydrographySourceConfig(source="bdtopage", page_size=2)
        gdf = fetch(cfg, self.BBOX)
        assert len(gdf) == 3  # 2 + 1
        assert mock_get.call_count == 3  # hits + 2 pages

    @patch("hydromodpy.core.io.http_client.HTTPClient.get")
    def test_custom_typename(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch

        hits_resp = MagicMock()
        hits_resp.content = self._hits_xml(1)
        hits_resp.raise_for_status = MagicMock()

        data_resp = MagicMock()
        data_resp.json.return_value = self._features_json(1)
        data_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [hits_resp, data_resp]

        cfg = HydrographySourceConfig(source="bdtopage", typename="sa:CoursEau_FXX_Topage2019")
        fetch(cfg, self.BBOX)

        # Verify typename was used in both calls
        for call in mock_get.call_args_list:
            params = call[1].get("params", call[0][1] if len(call[0]) > 1 else {})
            if "typeNames" in params:
                assert params["typeNames"] == "sa:CoursEau_FXX_Topage2019"
