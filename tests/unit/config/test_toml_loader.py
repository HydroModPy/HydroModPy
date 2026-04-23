from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config.toml_loader import load_toml_with_base_config


def test_load_toml_with_base_config_merges_nested_sections(tmp_path: Path) -> None:
    base_path = tmp_path / "base.toml"
    child_path = tmp_path / "child.toml"

    base_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path / "demo"}"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
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


def test_load_toml_with_base_config_rejects_cycles(tmp_path: Path) -> None:
    first_path = tmp_path / "first.toml"
    second_path = tmp_path / "second.toml"

    first_path.write_text('base_config = "second.toml"\n', encoding="utf-8")
    second_path.write_text('base_config = "first.toml"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="circular base_config chain"):
        load_toml_with_base_config(first_path)


def test_hydromodpy_config_from_toml_supports_base_config(tmp_path: Path) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    base_path = tmp_path / "base.toml"
    child_path = tmp_path / "child.toml"

    base_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{tmp_path / "demo"}"',
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
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


def test_launcher_simulation_example_config_inheritance_keeps_only_relevant_data_types() -> None:
    example_config = (
        Path(__file__).resolve().parents[3]
        / "examples_legacy_2"
        / "projects"
        / "launcher_simulation"
        / "run_fast_mf6.toml"
    )

    payload = load_toml_with_base_config(example_config)

    assert payload["flow"]["active_bc"] == ["ocean", "drainage"]
    assert payload["data"]["types"] == ["recharge"]
    assert "hydrography" not in payload["data"]
    assert payload["data"]["oceanic"]["sources"][0]["source"] == "custom"
    assert payload["data"]["recharge"]["sources"][0]["source"] == "synthetic"


def test_launcher_simulation_mf6_precomputed_mesh_input_config_uses_runtime_mesh() -> None:
    example_config = (
        Path(__file__).resolve().parents[3]
        / "examples_legacy_2"
        / "projects"
        / "launcher_simulation"
        / "run_fast_mf6_precomputed_mesh_input.toml"
    )

    payload = load_toml_with_base_config(example_config)

    assert payload["mesh_input"]["mesh_path"] == "results_stable/mesh/mesh_catchment.msh"
    assert payload["mesh_input"]["bundle_dir"] == "results_stable/mesh/mesh_catchment_bundle"
    assert "planar" not in payload["modflow6"]["sgrid"]
    assert payload["modflow6"]["sgrid"]["vertical"]["nlay"] == 2
    assert payload["postprocess"]["flow"]["native_mesh_png"] is True


def test_launcher_simulation_mf6_mesh_catchment_config_embeds_mesh_generation() -> None:
    example_config = (
        Path(__file__).resolve().parents[3]
        / "examples_legacy_2"
        / "projects"
        / "launcher_simulation"
        / "run_fast_mf6_mesh_catchment.toml"
    )

    payload = load_toml_with_base_config(example_config)

    assert payload["mesh_catchment"]["constraints_mode"] == "geology_rivers"
    assert payload["simulation"]["run_id"] == "example12_fast_mf6_mesh_catchment"
    assert payload["simulation"]["process"][0]["solvers"] == ["modflow6"]
    assert payload["simulation"]["process"][1]["solvers"] == ["modflow6gwt"]
    assert payload["simulation"]["time"]["step_value"] == "10 day"
    assert payload["modflow6"]["tgrid"]["firstpersteady"] is False
    assert payload["flow"]["ic"]["type"] == "top"
    assert payload["flow"]["param"]["K"]["field_homogeneous"]["value"] == "1e-5 m/s"
    assert payload["flow"]["param"]["Sy"]["field_homogeneous"]["value"] == "0.12 -"
    assert payload["data"]["recharge"]["sources"][0]["freq"] == "10D"
    assert payload["postprocess"]["flow"]["display"] is True
    assert payload["postprocess"]["flow"]["native_mesh_png"] is True
    assert payload["capability_gallery"]["enabled"] is True
    assert payload["capability_gallery"]["case_slug"] == "modflow6_gmsh_mesh_catchment"

    cfg = HydroModPyConfig.from_toml(example_config)
    assert cfg.capability_gallery.enabled is True
    assert cfg.modflow6.tgrid is not None
    assert cfg.modflow6.tgrid.firstpersteady is False
    assert (
        cfg.capability_gallery.output_dir
        == (
            example_config.parent
            / "../../capability_gallery/launcher_simulation/modflow6_gmsh_mesh_catchment"
        ).resolve()
    )


def test_hydromodpy_config_loads_profiling_shortcuts(tmp_path: Path) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()
    config_path = tmp_path / "profile.toml"
    config_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "reuse_existing_outputs = true",
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.geographic.reuse_existing_outputs is True
