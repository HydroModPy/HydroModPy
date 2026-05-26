from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.variables.hydrometry.apis import hubeau


@pytest.mark.fast
def test_hubeau_fetch_limits_discovered_stations_before_downloading(monkeypatch):
    downloaded: list[str] = []

    def fake_discover(_bbox, **_kwargs):
        return ["J000000001", "J000000002", "J000000003"]

    def fake_location(station_id):
        return StationLocation(id=station_id, x=-1.0, y=48.0, crs="EPSG:4326")

    def fake_download(station_id, _product, _date_start, _date_end):
        downloaded.append(station_id)
        return pd.DataFrame(
            {
                "datetime": [pd.Timestamp("2020-01-01")],
                "value": [1.0],
            }
        )

    monkeypatch.setattr(hubeau, "_discover_stations_in_bbox", fake_discover)
    monkeypatch.setattr(hubeau, "_fetch_station_location", fake_location)
    monkeypatch.setattr(hubeau, "_download_observations", fake_download)

    records = hubeau.fetch(
        product="QmnJ",
        bbox=(-2.0, 47.0, -1.0, 48.0),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 2),
        max_stations=2,
    )

    assert downloaded == ["J000000001", "J000000002"]
    assert [record.station_id for record in records] == ["J000000001", "J000000002"]


@pytest.mark.fast
def test_hubeau_station_location_keeps_influence_metadata(monkeypatch):
    def fake_get_json(_url, params):
        assert params["code_station"] == "J000000001"
        return {
            "data": [
                {
                    "code_station": "J000000001",
                    "libelle_station": "Station influencee",
                    "longitude_station": -1.5,
                    "latitude_station": 48.1,
                    "coordonnee_x_station": 352000.0,
                    "coordonnee_y_station": 6812000.0,
                    "influence_generale_site": "1",
                    "commentaire_influence_generale_site": "Retenue en amont.",
                    "influence_locale_station": "0",
                }
            ]
        }

    monkeypatch.setattr(hubeau, "get_json", fake_get_json)

    location = hubeau._fetch_station_location("J000000001")

    assert location is not None
    assert location.metadata["influence_generale_site"] == "1"
    assert location.metadata["commentaire_influence_generale_site"] == "Retenue en amont."
    assert location.metadata["influence_locale_station"] == "0"
