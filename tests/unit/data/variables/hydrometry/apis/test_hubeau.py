"""Hub'Eau hydrometry: units of each product, station choice and station metadata.

A product is served in l/s or mm and stored in m3/s or m. One row per product
gives the unit the API serves, the unit the record keeps and what a served value
becomes.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.variables.hydrometry.apis import hubeau

# One row per product of PRODUCTS: served unit, stored unit, a served value and its SI value.
_PRODUCT_UNITS = [
    pytest.param("QmnJ", "l/s", "m3/s", 2500.0, 2.5, id="daily_mean_discharge"),
    pytest.param("QmM", "l/s", "m3/s", 2500.0, 2.5, id="monthly_mean_discharge"),
    pytest.param("QINnJ", "l/s", "m3/s", 40.0, 0.04, id="daily_minimum_discharge"),
    pytest.param("QINM", "l/s", "m3/s", 40.0, 0.04, id="monthly_minimum_discharge"),
    pytest.param("QIXnJ", "l/s", "m3/s", 12000.0, 12.0, id="daily_maximum_discharge"),
    pytest.param("QIXM", "l/s", "m3/s", 12000.0, 12.0, id="monthly_maximum_discharge"),
    pytest.param("HIXnJ", "mm", "m", 1850.0, 1.85, id="daily_maximum_level"),
    pytest.param("HIXM", "mm", "m", 1850.0, 1.85, id="monthly_maximum_level"),
]


def test_the_table_has_a_row_for_every_product() -> None:
    assert {param.values[0] for param in _PRODUCT_UNITS} == set(hubeau.PRODUCTS)


@pytest.mark.parametrize(("product", "served_unit", "unit", "served", "expected"), _PRODUCT_UNITS)
def test_a_served_value_is_stored_in_the_si_unit_of_its_product(
    monkeypatch, product, served_unit, unit, served, expected
) -> None:
    spec = hubeau.PRODUCTS[product]
    assert (spec.served_unit, spec.unit) == (served_unit, unit)
    payload = {
        "data": [
            {
                "date_obs_elab": "2020-01-02",
                "resultat_obs_elab": served,
                "libelle_qualification": "Bonne",
            },
            {
                "date_obs_elab": "2020-01-01",
                "resultat_obs_elab": 2.0 * served,
                "libelle_qualification": "Bonne",
            },
        ]
    }
    monkeypatch.setattr(hubeau, "get_json", lambda *_args, **_kwargs: payload)

    frame = hubeau._get_obs_chunk("J000000001", product, datetime(2020, 1, 1), datetime(2020, 1, 2))

    assert frame["value"].tolist() == pytest.approx([2.0 * expected, expected])
    assert frame["datetime"].is_monotonic_increasing


def test_a_missing_or_unreadable_value_is_dropped_and_not_converted_to_zero(monkeypatch) -> None:
    payload = {
        "data": [
            {"date_obs_elab": "2020-01-01", "resultat_obs_elab": None},
            {"date_obs_elab": "2020-01-02", "resultat_obs_elab": "n/a"},
            {"date_obs_elab": "2020-01-03", "resultat_obs_elab": 1000.0},
        ]
    }
    monkeypatch.setattr(hubeau, "get_json", lambda *_args, **_kwargs: payload)

    frame = hubeau._get_obs_chunk("J000000001", "QmnJ", datetime(2020, 1, 1), datetime(2020, 1, 3))

    assert frame["value"].tolist() == [1.0]


def test_an_empty_answer_is_an_empty_frame(monkeypatch) -> None:
    monkeypatch.setattr(hubeau, "get_json", lambda *_args, **_kwargs: {"data": []})

    frame = hubeau._get_obs_chunk("J000000001", "QmnJ", datetime(2020, 1, 1), datetime(2020, 1, 3))

    assert frame.empty


@pytest.mark.fast
def test_max_stations_limits_the_download(monkeypatch):
    downloaded: list[str] = []

    def fake_discover(_bbox, **_kwargs):
        return ["J000000001", "J000000002", "J000000003"]

    def fake_location(station_id, **_kwargs):
        return StationLocation(id=station_id, x=-1.0, y=48.0, crs="EPSG:4326")

    def fake_download(station_id, _product, _date_start, _date_end, **_kwargs):
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
def test_station_location_keeps_influence_metadata(monkeypatch):
    def fake_get_json(_client, _url, params, **_kw):
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
