from __future__ import annotations

import pytest

from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.spatial.geographic import GeographicConfig


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


def test_hydromodpy_config_accepts_matching_streams_with_synthetic_geographic(
    tmp_path,
):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[workspace]",
                f'project_root = "{tmp_path}"',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
                "",
                "[postprocess]",
                "enabled = true",
                "",
                "[postprocess.flow]",
                "enabled = true",
                "matching_streams = true",
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)

    assert cfg.geographic.uses_synthetic_geographic() is True
    # Postprocess legacy nested options are accepted but no longer interpreted.
    assert cfg.postprocess.enabled is True
