from __future__ import annotations

from pathlib import Path

from hydromodpy_annex.preprocess.catchment_identification_scan.config import (
    CatchmentIdentificationConfig,
)


def test_catchment_identification_config_supports_base_config(tmp_path: Path) -> None:
    dem_path = tmp_path / "data" / "dem.tif"
    dem_path.parent.mkdir(parents=True, exist_ok=True)
    dem_path.write_text("dummy", encoding="utf-8")

    base_config_path = tmp_path / "config_base.toml"
    base_config_path.write_text(
        "\n".join(
            [
                "[catchment_identification_scan]",
                'dem_path = "data/dem.tif"',
                'output_dir = "outputs/base"',
                'outlets_csv_name = "selected_outlets.csv"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    override_config_path = tmp_path / "config_override.toml"
    override_config_path.write_text(
        "\n".join(
            [
                'base_config = "config_base.toml"',
                "",
                "[catchment_identification_scan]",
                'output_dir = "scenario_a/identification"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = CatchmentIdentificationConfig.from_toml(override_config_path)

    assert cfg.dem_path == dem_path.resolve()
    assert cfg.output_dir == (tmp_path / "scenario_a" / "identification").resolve()
    assert cfg.outlets_csv_name == "selected_outlets.csv"
