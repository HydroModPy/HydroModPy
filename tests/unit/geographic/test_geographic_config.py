from __future__ import annotations

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.spatial.geographic import GeographicConfig
from hydromodpy.spatial.geographic.geographic_config import (
    normalize_geographic_catchment_payload,
)


def test_geographic_config_txt_accepts_cell_size_with_unit_string():
    cfg = GeographicConfig.model_validate(
        {
            "catch_def": "txt",
            "dem_init_path": "dem.xyz",
            "cell_size": "150.0 m",
        }
    )
    assert float(cfg.cell_size) == pytest.approx(150.0)


def test_geographic_flat_payload_normalization_is_centralized() -> None:
    payload = {
        "catch_def": "from_outlet_coord",
        "dem_init_path": "dem.tif",
        "x_outlet": 1.0,
        "y_outlet": 2.0,
        "snap_dist": "50 m",
        "buff_area": "10%",
        "catchment": {"buff_area": "20%"},
    }

    normalized = normalize_geographic_catchment_payload(payload)

    assert "catch_def" not in normalized
    assert normalized["catchment"]["catch_def"] == "from_outlet_coord"
    assert normalized["catchment"]["dem_init_path"] == "dem.tif"
    assert normalized["catchment"]["buff_area"] == "20%"


def test_geographic_config_txt_accepts_cell_size_with_km_unit():
    cfg = GeographicConfig.model_validate(
        {
            "catch_def": "txt",
            "dem_init_path": "dem.xyz",
            "cell_size": "0.15 km",
        }
    )
    assert float(cfg.cell_size) == pytest.approx(150.0)


def test_geographic_config_synthetic_mode_accepts_missing_standard_fields():
    cfg = GeographicConfig.model_validate(
        {
            "source_mode": "synthetic",
        }
    )

    assert cfg.uses_synthetic_geographic() is True
    assert cfg.catch_def is None
    assert cfg.synthetic.case_id == "flat20"


def test_geographic_config_standard_mode_requires_catch_def():
    with pytest.raises(
        ValueError,
        match="geographic.catch_def is required when geographic.source_mode='standard'",
    ):
        GeographicConfig.model_validate({"source_mode": "standard"})


def test_hydromodpy_config_accepts_synthetic_geographic(
    tmp_path,
):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path}"',
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)

    assert cfg.geographic.uses_synthetic_geographic() is True
