from __future__ import annotations

from pathlib import Path

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.solver.modflow_nwt.modflow_config import (
    ModflowConfig,
    ModflowSpecifParams,
)


def test_modflow_config_defaults_match_runtime_defaults():
    cfg = ModflowConfig()
    runtime = ModflowSpecifParams.from_config(cfg)

    assert runtime.mf_version == "mfnwt"
    assert runtime.nwt_headtol == 1e-4
    assert runtime.nwt_fluxtol == 500.0
    assert runtime.vka == 1.0
    assert runtime.exdp == 1.0


def test_hydromodpy_config_loads_modflow_section(tmp_path: Path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[initializing]",
                'catch_name = "demo"',
                'out_dir_path = "out"',
                'data_path = "data"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
                "[modflow]",
                "vka = 2.5",
                "exdp = 3.0",
                'nwt_options = "SIMPLE"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)

    assert cfg.modflow.vka == 2.5
    assert cfg.modflow.exdp == 3.0
    assert cfg.modflow.nwt_options == "SIMPLE"
