"""Unit tests for water quality Hub'Eau API adapter (mocked)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.data.variables.water_quality.apis import hubeau as hubeau_api
from hydromodpy.data.variables.water_quality.apis.hubeau import (
    _normalize_dataframe,
    fetch,
)


class TestNormalizeDataframe:
    def test_river_dataframe(self):
        df = pd.DataFrame(
            {
                "date_prelevement": ["2020-01-15", "2020-02-10"],
                "libelle_parametre": ["pH", "Nitrates"],
                "resultat": [7.2, 15.3],
                "symbole_unite": ["U pH", "mg/L"],
            }
        )
        out = _normalize_dataframe(df, is_river=True)
        assert len(out) == 2
        assert "datetime" in out.columns
        assert "parameter" in out.columns
        assert "value" in out.columns
        assert "unit" in out.columns
        assert out["parameter"].iloc[0] == "pH"

    def test_piezometer_dataframe(self):
        df = pd.DataFrame(
            {
                "date_debut_prelevement": ["2020-03-01"],
                "nom_param": ["Conductivite"],
                "resultat": [450.0],
                "nom_unite": ["uS/cm"],
            }
        )
        out = _normalize_dataframe(df, is_river=False)
        assert len(out) == 1
        assert out["parameter"].iloc[0] == "Conductivite"

    def test_empty_dataframe(self):
        out = _normalize_dataframe(pd.DataFrame(), is_river=True)
        assert out.empty


class TestFetchMocked:
    def test_fetch_with_mocked_api(self, monkeypatch):
        """Test fetch logic with mocked get_json calls."""
        call_count = {"n": 0}

        def fake_get_json(url, *, params=None, **kwargs):
            call_count["n"] += 1
            if "station_pc" in url or "stations" in url:
                return {
                    "data": [
                        {
                            "code_station": "R1",
                            "longitude": 2.35,
                            "latitude": 48.85,
                            "libelle_station": "River 1",
                        }
                    ]
                }
            # analyses endpoint
            return {
                "data": [
                    {
                        "date_prelevement": "2020-01-15",
                        "libelle_parametre": "pH",
                        "resultat": 7.2,
                        "symbole_unite": "U pH",
                    },
                    {
                        "date_prelevement": "2020-02-10",
                        "libelle_parametre": "Nitrates",
                        "resultat": 12.0,
                        "symbole_unite": "mg/L",
                    },
                ]
            }

        monkeypatch.setattr(hubeau_api, "get_json", fake_get_json)

        records = fetch(
            site_type="river",
            station_ids=["R1"],
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 3, 31),
        )

        assert len(records) == 2
        variables = {r.variable for r in records}
        assert "pH" in variables
        assert "Nitrates" in variables
        assert records[0].source == "hubeau"
        assert records[0].location is not None
