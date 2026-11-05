"""The sites of a summary table are written in one CRS."""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.results.export.summary_tables import in_one_crs


def test_sites_in_several_crs_are_all_written_in_wgs84() -> None:
    by_site = pd.DataFrame(
        {
            "crs": ["EPSG:2154", "EPSG:4326", None],
            "x_outlet": [389285.9, -1.7, None],
            "y_outlet": [6816518.7, 48.1, None],
        }
    )

    out = in_one_crs(by_site)

    assert set(out["crs"]) == {"EPSG:4326"}
    assert out["x_outlet"][0] == pytest.approx(-1.2, abs=0.1)
    assert out["y_outlet"][0] == pytest.approx(48.2, abs=0.5)
    assert out["x_outlet"][1] == -1.7
    assert pd.isna(out["x_outlet"][2])


def test_sites_in_one_crs_are_left_as_they_are() -> None:
    by_site = pd.DataFrame(
        {"crs": ["EPSG:2154"] * 2, "x_outlet": [1.0, 2.0], "y_outlet": [3.0, 4.0]}
    )

    assert in_one_crs(by_site) is by_site
