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
