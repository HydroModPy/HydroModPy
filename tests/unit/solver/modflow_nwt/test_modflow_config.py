from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.solver.base.solver_engine import SolverEngine
from hydromodpy.solver.modflow_nwt.modflow import (
    ModflowConfig,
    ModflowSpecifParams,
)
from hydromodpy.solver.utils.temporal.tmesh_config import TMeshConfig
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import SolverSGridConfig


def test_modflow_config_defaults_match_runtime_defaults():
    cfg = ModflowConfig()
    params = ModflowSpecifParams.from_config(cfg)

    assert params.runtime.mf_version == "mfnwt"
    assert params.runtime.nwt_headtol == 1e-4
    assert params.runtime.nwt_fluxtol == 500.0
    assert params.process_specific.vka == 1.0
    assert params.process_specific.exdp == 1.0
    assert isinstance(params.sgrid, SolverSGridConfig)
    assert params.sgrid.planar.mode == "keep_native"
    assert params.sgrid.vertical.nlay == 1
    assert params.tgrid is None


def test_modflow_config_accepts_exdp_with_unit_string():
    cfg = ModflowConfig.model_validate(
        {
            "process_specific": {
                "vka": 1.0,
                "exdp": "1.5 m",
            }
        }
    )
    assert cfg.process_specific.exdp == pytest.approx(1.5)


def test_hydromodpy_config_loads_modflow_nested_sections(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path}"',
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
                "[solver]",
                'solver_engine = "modflownwt"',
                "",
                "[modflownwt.runtime]",
                'nwt_options = "SIMPLE"',
                "",
                "[modflownwt.process_specific]",
                "vka = 2.5",
                "exdp = 3.0",
                "",
                "[modflownwt.sgrid.planar]",
                'mode = "resample_to_shape"',
                "nx = 6",
                "ny = 5",
                'resampling = "nearest"',
                "",
                "[modflownwt.sgrid.vertical]",
                'genmtd_lay = "decay"',
                "nlay = 3",
                "lay_decay = 1.8",
                "",
                "[modflownwt.tgrid]",
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

    assert cfg.solver.solver_engine == SolverEngine.MODFLOW_NWT
    assert cfg.modflownwt.process_specific.vka == 2.5
    assert cfg.modflownwt.process_specific.exdp == 3.0
    assert cfg.modflownwt.runtime.nwt_options == "SIMPLE"
    assert isinstance(cfg.modflownwt.sgrid, SolverSGridConfig)
    assert cfg.modflownwt.sgrid.planar.mode == "resample_to_shape"
    assert cfg.modflownwt.sgrid.planar.nx == 6
    assert cfg.modflownwt.sgrid.planar.ny == 5
    assert cfg.modflownwt.sgrid.planar.resampling == "nearest"
    assert cfg.modflownwt.sgrid.vertical.genmtd_lay == "decay"
    assert cfg.modflownwt.sgrid.vertical.nlay == 3
    assert cfg.modflownwt.sgrid.vertical.lay_decay == 1.8
    assert isinstance(cfg.modflownwt.tgrid, TMeshConfig)
    assert cfg.modflownwt.tgrid.flow_regime == "transient"
    assert cfg.modflownwt.tgrid.nper == 4
    assert cfg.modflownwt.tgrid.ntsp == [1, 2, 2, 3]


def test_hydromodpy_config_rejects_legacy_flat_sgrid_payload(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path}"',
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
                "[solver]",
                'solver_engine = "modflownwt"',
                "",
                "[modflownwt.sgrid]",
                'genmtd_lay = "decay"',
                "nlay = 4",
                "lay_decay = 1.5",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        HydroModPyConfig.from_toml(toml_path)


def test_hydromodpy_config_rejects_legacy_planar_mode_aliases(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path}"',
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
                "[solver]",
                'solver_engine = "modflownwt"',
                "",
                "[modflownwt.sgrid.planar]",
                'mode = "shape"',
                "nx = 6",
                "ny = 5",
                "",
                "[modflownwt.sgrid.vertical]",
                'genmtd_lay = "constant"',
                "nlay = 1",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="resample_to_shape"):
        HydroModPyConfig.from_toml(toml_path)


def test_hydromodpy_config_loads_modflow_exdp_with_unit_string(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path}"',
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
                "[solver]",
                'solver_engine = "modflownwt"',
                "",
                "[modflownwt.process_specific]",
                "vka = 2.5",
                'exdp = "3.0 m"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)
    assert cfg.modflownwt.process_specific.exdp == pytest.approx(3.0)


def test_hydromodpy_config_rejects_legacy_flat_modflow_schema(tmp_path: Path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path}"',
                f'root = "{tmp_path}"',
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


def test_hydromodpy_config_loads_independent_modflow6_runtime(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path}"',
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
                "[solver]",
                'solver_engine = "modflow6"',
                "",
                "[modflow6.runtime]",
                'mf6_executable_name = "mf6_custom"',
                'mf6_ims_complexity = "SIMPLE"',
                "mf6_enable_rewet = true",
                "mf6_rewet_wetdry = 0.05",
                "",
                "[modflow6.process_specific]",
                "evt_extinction_depth = 2.5",
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)
    assert cfg.solver.solver_engine == SolverEngine.MODFLOW6
    assert cfg.modflow6.runtime.mf6_executable_name == "mf6_custom"
    assert cfg.modflow6.runtime.mf6_ims_complexity == "SIMPLE"
    assert cfg.modflow6.runtime.mf6_enable_rewet is True
    assert cfg.modflow6.runtime.mf6_rewet_wetdry == pytest.approx(0.05)
    assert cfg.modflow6.process_specific.evt_extinction_depth == pytest.approx(2.5)
