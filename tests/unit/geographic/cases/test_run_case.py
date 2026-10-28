"""The reference delineation case prints the summary it builds."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.geographic.cases.reference_catchment_delineation_case import run_case

pytestmark = pytest.mark.fast


def test_main_prints_every_key_of_a_case_summary(monkeypatch, capsys):
    summary = {
        "project_root": "/projects/base",
        "watershed_shp": "watershed.shp",
        "watershed_box_buff_dem": "dem.tif",
        "shape_box_buff_dem": (3, 4),
        "catchment_area_km2": 12.5,
        "mean_elevation_catchment_m": 101.0,
        "figure": None,
    }
    monkeypatch.setattr(
        run_case, "run_geographic_cases_from_toml", lambda *args, **kwargs: {"base": summary}
    )

    assert run_case.main(["--cases", "base", "--no-show-plot"]) == 0

    printed = capsys.readouterr().out
    assert "[base] project_root=/projects/base" in printed
    assert "[base] shape_box_buff_dem=3x4" in printed
