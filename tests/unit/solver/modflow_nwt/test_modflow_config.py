from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.solver.modflow_nwt.modflow_config import (
    ModflowConfig,
    ModflowSpecifParams,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import VerticalGridConfig
from hydromodpy.solver.utils.temporal.tmesh_config import TMeshConfigModel


def test_modflow_config_defaults_match_runtime_defaults():
    cfg = ModflowConfig()
    params = ModflowSpecifParams.from_config(cfg)

    assert params.runtime.mf_version == "mfnwt"
    assert params.runtime.nwt_headtol == 1e-4
    assert params.runtime.nwt_fluxtol == 500.0
    assert params.process_specific.vka == 1.0
    assert params.process_specific.exdp == 1.0
    assert params.sgrid is None
    assert params.tgrid is None


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
                "",
                "[modflow.tgrid]",
                'itmuni = "d"',
                'flow_regime = "transient"',
                'genmtd = "synthetic_regular"',
                "nper = 4",
                "lenper = 2.0",
                "firstpersteady = true",
                "ntsp = [1, 2, 2, 3]",
                "tsmult = [1.0, 1.1, 1.1, 1.2]",
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)

    assert cfg.modflow.process_specific.vka == 2.5
    assert cfg.modflow.process_specific.exdp == 3.0
    assert cfg.modflow.runtime.nwt_options == "SIMPLE"
    assert isinstance(cfg.modflow.sgrid, VerticalGridConfig)
    assert cfg.modflow.sgrid.genmtd_lay == "decay"
    assert cfg.modflow.sgrid.nlay == 3
    assert cfg.modflow.sgrid.lay_decay == 1.8
    assert isinstance(cfg.modflow.tgrid, TMeshConfigModel)
    assert cfg.modflow.tgrid.flow_regime == "transient"
    assert cfg.modflow.tgrid.nper == 4
    assert cfg.modflow.tgrid.ntsp == [1, 2, 2, 3]


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
