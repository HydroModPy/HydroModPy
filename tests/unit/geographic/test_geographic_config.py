from __future__ import annotations

import pytest

from hydromodpy.geographic import GeographicConfig


def test_geographic_config_txt_accepts_cell_size_with_unit_string():
    cfg = GeographicConfig.model_validate(
        {
            "catch_def": "txt",
            "dem_init_path": "dem.xyz",
            "cell_size": "150.0 m",
        }
    )
    assert float(cfg.cell_size) == pytest.approx(150.0)


def test_geographic_config_txt_accepts_cell_size_with_km_unit():
    cfg = GeographicConfig.model_validate(
        {
            "catch_def": "txt",
            "dem_init_path": "dem.xyz",
            "cell_size": "0.15 km",
        }
    )
    assert float(cfg.cell_size) == pytest.approx(150.0)

