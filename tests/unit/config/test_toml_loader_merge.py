from __future__ import annotations

from pathlib import Path

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


def test_load_toml_with_base_config_merges_nested_sections(tmp_path: Path) -> None:
    base_path = tmp_path / "base.toml"
    child_path = tmp_path / "child.toml"

    base_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path / "demo"}"',
                "",
                "[geographic]",
                "",
                "[geographic.catchment]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "[flow]",
                'active_bc = ["ocean"]',
                "",
                "[flow.bc.dirichlet.ocean]",
                'value = "1.0 m"',
                "data_value = true",
            ]
        ),
        encoding="utf-8",
    )
    child_path.write_text(
        "\n".join(
            [
                'base_config = "base.toml"',
                "",
                "[flow]",
                'active_bc = ["ocean", "drainage"]',
                "",
                "[flow.bc.cauchy.drainage]",
                'value = "0.0 m2/s"',
                'application_domain = "top"',
            ]
        ),
        encoding="utf-8",
    )

    payload = load_toml_with_base_config(child_path)

    assert payload["workspace"]["project_root"] == str(tmp_path / "demo")
    assert payload["flow"]["active_bc"] == ["ocean", "drainage"]
    assert payload["flow"]["bc"]["dirichlet"]["ocean"]["data_value"] is True
    assert payload["flow"]["bc"]["cauchy"]["drainage"]["application_domain"] == "top"


def test_hydromodpy_config_from_toml_supports_base_config(tmp_path: Path) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    base_path = tmp_path / "base.toml"
    child_path = tmp_path / "child.toml"

    base_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path / "demo"}"',
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                "",
                "[geographic.catchment]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "[flow]",
                'active_bc = ["ocean"]',
                "",
                "[flow.bc.dirichlet.ocean]",
                'value = "1.0 m"',
                "data_value = true",
            ]
        ),
        encoding="utf-8",
    )
    child_path.write_text(
        "\n".join(
            [
                'base_config = "base.toml"',
                "",
                "[flow]",
                'active_bc = ["ocean", "drainage"]',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(child_path)

    assert cfg.workspace.catch_name == "demo"
    assert str(cfg.geographic.dem_init_path) == str(dem_path.resolve())
    assert cfg.flow.active_bc == ["ocean", "drainage"]
