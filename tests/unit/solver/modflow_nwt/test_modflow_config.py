from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.solver.modflow_nwt.modflow_config import (
    ModflowConfig,
    ModflowSpecifParams,
)


def test_modflow_config_defaults_match_runtime_defaults():
    cfg = ModflowConfig()
    params = ModflowSpecifParams.from_config(cfg)

    assert params.runtime.mf_version == "mfnwt"
    assert params.runtime.nwt_headtol == 1e-4
    assert params.runtime.nwt_fluxtol == 500.0
    assert params.process_specific.vka == 1.0
    assert params.process_specific.exdp == 1.0
    assert params.sgrid is None


def test_hydromodpy_config_loads_modflow_nested_sections(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[workspace]",
                'catch_name = "demo"',
                'out_dir_path = "out"',
                'data_path = "data"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
                "[modflow.runtime]",
                'nwt_options = "SIMPLE"',
                "",
                "[modflow.process_specific]",
                "vka = 2.5",
                "exdp = 3.0",
                "",
                "[modflow.sgrid]",
                'lenuni = "m"',
                "nodata = -9999.0",
                'genmtd_lay = "decay"',
                "nlay = 3",
                "lay_decay = 1.8",
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)

    assert cfg.modflow.process_specific.vka == 2.5
    assert cfg.modflow.process_specific.exdp == 3.0
    assert cfg.modflow.runtime.nwt_options == "SIMPLE"
    assert cfg.modflow.sgrid["genmtd_lay"] == "decay"
    assert cfg.modflow.sgrid["nlay"] == 3
    assert cfg.modflow.sgrid["lay_decay"] == 1.8


def test_hydromodpy_config_rejects_legacy_flat_modflow_schema(tmp_path: Path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[workspace]",
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

    with pytest.raises(ValueError):
        HydroModPyConfig.from_toml(toml_path)
