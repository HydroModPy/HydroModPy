"""Unit tests for water quality Hub'Eau API adapter (mocked)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.data.variables.water_quality.apis.hubeau import _normalize_dataframe


class TestNormalizeDataframe:
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
