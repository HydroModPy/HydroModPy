"""Hub'Eau water quality answers, normalized to a frame with a parameter column."""

from __future__ import annotations

import pandas as pd

from hydromodpy.data.variables.water_quality.apis.hubeau import _normalize_dataframe


def test_piezometer_frame_is_normalized():
    frame = pd.DataFrame(
        {
            "date_debut_prelevement": ["2020-03-01"],
            "nom_param": ["Conductivite"],
            "resultat": [450.0],
            "nom_unite": ["uS/cm"],
        }
    )

    out = _normalize_dataframe(frame, is_river=False)

    assert len(out) == 1
    assert out["parameter"].iloc[0] == "Conductivite"


def test_empty_frame_stays_empty():
    assert _normalize_dataframe(pd.DataFrame(), is_river=True).empty
