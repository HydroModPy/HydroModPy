"""The hydrography providers: BD TOPAGE, EU-Hydro and OSM."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from unittest.mock import MagicMock, patch

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import DataRequestError, DataSourceError
from hydromodpy.data.common.clients import sandre_topage
from hydromodpy.data.source.permanence import PERMANENCE_COLUMN
from hydromodpy.data.variables.hydrography.apis import bdtopage
from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

pytestmark = pytest.mark.fast


def _reaches(**columns: Sequence[object]) -> gpd.GeoDataFrame:
    n = len(next(iter(columns.values()))) if columns else 1
    return gpd.GeoDataFrame(
        {"gid": list(range(n)), **columns},
        geometry=[LineString([(350000.0 + i, 6800000.0), (350010.0, 6800010.0)]) for i in range(n)],
        crs="EPSG:2154",
    )


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Stub the client: record each question and answer with three reaches."""
    questions: list[dict] = []

    def _get_features(typename: str, bbox: tuple, *, page_size: int) -> gpd.GeoDataFrame:
        questions.append({"typename": typename, "bbox": bbox, "page_size": page_size})
        return _reaches(PersistanceTH=["permanent", "intermittent", "permanent"])

    monkeypatch.setattr(sandre_topage, "get_features", _get_features)
    return questions


def test_the_one_layer_is_every_reach_of_metropolitan_france() -> None:
    assert bdtopage.LAYER == "sa:TronconHydrographique_FXX_Topage2026"
    assert bdtopage.BdTopageSource().metadata() == {"typename": bdtopage.LAYER}


def test_the_sandre_vocabulary_maps_onto_the_canonical_one() -> None:
    native = ["permanent", "intermittent", "éphémère", "sec", "inconnue"]
    frame = bdtopage.with_permanence(_reaches(PersistanceTH=native))

    assert frame[PERMANENCE_COLUMN].tolist() == [
        "permanent",
        "intermittent",
        "ephemeral",
        "dry",
        "unknown",
    ]
    assert frame["PersistanceTH"].tolist() == native, "the native attribute stays as it came"


def test_a_value_the_sandre_never_wrote_is_unknown_and_named(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    frame = bdtopage.with_permanence(_reaches(PersistanceTH=["saisonnier", None]))

    assert frame[PERMANENCE_COLUMN].tolist() == ["unknown", "unknown"]
    assert "saisonnier" in caplog.text


def test_reaches_without_their_persistence_mean_the_layer_changed() -> None:
    with pytest.raises(DataSourceError, match="PersistanceTH"):
        bdtopage.with_permanence(_reaches(TopoOH=["le Val"]))


def test_no_reach_is_not_an_error() -> None:
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:2154")

    assert bdtopage.with_permanence(empty).empty


def test_the_source_asks_its_layer_over_the_lambert93_box(asked: list[dict]) -> None:
    box = (346361.0, 6797325.0, 363915.0, 6821726.0)
    frame = bdtopage.BdTopageSource(page_size=17).download(box)

    assert asked == [{"typename": bdtopage.LAYER, "bbox": box, "page_size": 17}]
    assert frame[PERMANENCE_COLUMN].tolist() == ["permanent", "intermittent", "permanent"]
    assert bdtopage.BdTopageSource.extent_crs == "EPSG:2154"


def test_a_wgs84_caller_gets_degrees_back_and_asks_a_box_that_holds_its_own(
    asked: list[dict],
) -> None:
    from pyproj import Transformer

    frame = bdtopage.fetch(HydrographySourceConfig(source="bdtopage"), (-1.8, 48.1, -1.5, 48.4))

    assert str(frame.crs) == "EPSG:4326"
    (question,) = asked
    assert question["typename"] == bdtopage.LAYER
    to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    xmin, ymin, xmax, ymax = question["bbox"]
    for lon, lat in [(-1.8, 48.1), (-1.8, 48.4), (-1.5, 48.1), (-1.5, 48.4)]:
        x, y = to_l93.transform(lon, lat)
        assert xmin <= x <= xmax and ymin <= y <= ymax


@pytest.mark.parametrize("page_size", [0, -1, True, 2.5])
def test_a_page_size_that_never_advances_is_refused(page_size: object) -> None:
    with pytest.raises(DataRequestError, match="page_size"):
        bdtopage.BdTopageSource(page_size=page_size)  # type: ignore[arg-type]


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

    @patch("hydromodpy.core.io.fetch.HTTPClient.get")
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

    @patch("hydromodpy.core.io.fetch.HTTPClient.get")
    def test_no_layers_found(self, mock_get):
        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch

        ms_resp = MagicMock()
        ms_resp.json.return_value = {"layers": []}
        ms_resp.raise_for_status = MagicMock()
        mock_get.return_value = ms_resp

        cfg = HydrographySourceConfig(source="euhydro")
        gdf = fetch(cfg, self.BBOX)
        assert gdf.empty

    @patch("hydromodpy.core.io.fetch.HTTPClient.get")
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

    @patch("hydromodpy.core.io.fetch.HTTPClient.get")
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

    @patch("hydromodpy.core.io.fetch.HTTPClient.get")
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

    @patch("hydromodpy.core.io.fetch.HTTPClient.get")
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

    @patch("hydromodpy.core.io.fetch.HTTPClient.get")
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

    @patch("hydromodpy.core.io.fetch.HTTPClient.get")
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
