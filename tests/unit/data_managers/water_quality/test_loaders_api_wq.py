from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from hydromodpy.data_managers.water_quality.loaders_api import ApiWaterQualityLoader


def _make_resp(status_code: int, data: list):
    resp = SimpleNamespace()
    resp.status_code = status_code
    resp.json = lambda: {"data": data}
    return resp


def test_get_station_info_river(monkeypatch):
    loader = ApiWaterQualityLoader(site_type="river")
    sample = {"code_station": "R1", "libelle_station": "River 1"}

    def fake_get(url, params=None, timeout=None):
        return _make_resp(200, [sample])

    monkeypatch.setattr("requests.get", fake_get)
    out = loader._get_station_info("R1")
    assert isinstance(out, dict)
    assert out.get("code_station") == "R1"


def test_get_station_info_piezometer(monkeypatch):
    loader = ApiWaterQualityLoader(site_type="pz")
    sample = {"code_bss": "PZ1", "nom_station": "PZ One", "geometry": {"coordinates": [1.0, 2.0]}}

    def fake_get(url, params=None, timeout=None):
        return _make_resp(200, [sample])

    monkeypatch.setattr("requests.get", fake_get)
    out = loader._get_station_info("PZ1")
    assert out.get("code_bss") == "PZ1"


def test_build_metadata_and_dates(monkeypatch):
    loader = ApiWaterQualityLoader(site_type="pz")
    station_info = {
        "libelle_station": "My Station",
        "geometry": {"coordinates": [10.0, 50.0]},
        "date_debut_mesure": "2020-01-01",
    }
    meta = loader._build_metadata("S1", station_info)
    assert meta["site_id"] == "S1"
    assert isinstance(meta["start_date"], datetime)
    assert meta["x_wgs84"] == 10.0
    assert meta["y_wgs84"] == 50.0


def test_get_time_series_single_year(monkeypatch):
    loader = ApiWaterQualityLoader(site_type="pz")
    # small date window
    loader.date_start = datetime(2020, 1, 1)
    loader.date_end = datetime(2020, 1, 2)

    sample_record = {"date_prelevement": "2020-01-01", "resultat": 42, "libelle_parametre": "param"}

    def fake_get(url, params=None, timeout=None):
        return _make_resp(200, [sample_record])

    monkeypatch.setattr("requests.get", fake_get)
    df, missing = loader._get_time_series("S1")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "date_measure" in df.columns
    assert df["site_id"].iloc[0] == "S1"
