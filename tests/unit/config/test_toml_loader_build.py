from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.config import HydroModPyConfig


def test_from_dict_keeps_api_workspace_default(tmp_path: Path) -> None:
    cfg = HydroModPyConfig.from_dict(
        {
            "workflow": {"mode": "simulation"},
            "geographic": {"source_mode": "synthetic"},
        },
        base_dir=tmp_path,
    )

    assert cfg.workspace.project_root == tmp_path.resolve()


def test_hydromodpy_config_loads_profiling_shortcuts(tmp_path: Path) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()
    config_path = tmp_path / "profile.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'root = "{tmp_path}"',
                f'project_root = "{tmp_path}"',
                "",
                "[geographic]",
                "reuse_existing_outputs = true",
                "",
                "[geographic.catchment]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.geographic.reuse_existing_outputs is True


def test_hydromodpy_config_allows_dem_from_data_sources_without_placeholder(
    tmp_path: Path,
) -> None:
    dem_path = tmp_path / "data" / "dem" / "dem.tif"
    dem_path.parent.mkdir(parents=True)
    dem_path.touch()
    config_path = tmp_path / "data_dem.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "",
                "[workspace]",
                f'root = "{tmp_path}"',
                f'project_root = "{tmp_path}"',
                f'data_dir = "{tmp_path / "data"}"',
                "",
                "[geographic]",
                "",
                "[geographic.catchment]",
                'catch_def = "dem"',
                "[data.dem]",
                "",
                "[[data.dem.sources]]",
                'source = "custom"',
                'path = "dem.tif"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.geographic.dem_init_path is None
    assert cfg.data.dem is not None
    assert cfg.data.dem.sources[0].path == dem_path.resolve()


def test_hydromodpy_config_loads_calibration_section(tmp_path: Path) -> None:
    """[calibration] in TOML must populate cfg.calibration via the section loader."""
    config_path = tmp_path / "calib.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "calibration"',
                "[workspace]",
                f'root = "{tmp_path}"',
                f'project_root = "{tmp_path}"',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
                "",
                "[flow]",
                'param_list = ["K"]',
                "",
                "[flow.param.K.field]",
                'kind = "homogeneous"',
                'value = "1.0e-4 m/s"',
                "",
                "[calibration]",
                'method = "random_search"',
                "max_iter = 7",
                "",
                "[calibration.parameters.K]",
                "bounds = [1.0e-6, 1.0e-3]",
                'target = "flow.param.K.field.value"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.calibration is not None
    assert cfg.calibration.method == "random_search"
    assert cfg.calibration.max_iter == 7
    assert "K" in cfg.calibration.parameters


def test_hydromodpy_config_calibration_absent_yields_none(tmp_path: Path) -> None:
    config_path = tmp_path / "no_calib.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'root = "{tmp_path}"',
                f'project_root = "{tmp_path}"',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.calibration is None


def test_hydromodpy_config_ignores_empty_site_selection_placeholder(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "empty_site_selection.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'root = "{tmp_path}"',
                f'project_root = "{tmp_path}"',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
                "",
                "[site_selection]",
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.site_selection is None


def test_hydromodpy_config_from_dict_resolves_nested_geographic_catchment(
    tmp_path: Path,
) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    cfg = HydroModPyConfig.from_dict(
        {
            "workflow": {"mode": "simulation"},
            "workspace": {"root": str(tmp_path), "project_root": ""},
            "geographic": {
                "catchment": {
                    "catch_def": "dem",
                    "dem_init_path": "dem.tif",
                }
            },
            "flow": {
                "param": {
                    "K": {
                        "field": {"kind": "homogeneous", "value": "1.0e-4 m/s"},
                    }
                }
            },
        },
        base_dir=tmp_path,
    )

    assert cfg.workspace.project_root == tmp_path.resolve()
    assert cfg.geographic.dem_init_path == dem_path.resolve()
    assert cfg.flow.param_list == ["K"]
    assert cfg.flow.param["K"].resolved_payload(param_id="K") == {
        "id": "K",
        "kind": "homogeneous",
        "value": "1.0e-4 m/s",
    }


def test_hydromodpy_config_from_json_resolves_nested_geographic_catchment(
    tmp_path: Path,
) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()
    payload = {
        "workflow": {"mode": "simulation"},
        "workspace": {"root": str(tmp_path), "project_root": str(tmp_path)},
        "geographic": {
            "catchment": {
                "catch_def": "dem",
                "dem_init_path": "dem.tif",
            }
        },
    }

    cfg = HydroModPyConfig.from_json(json.dumps(payload), base_dir=tmp_path)

    assert cfg.geographic.dem_init_path == dem_path.resolve()
