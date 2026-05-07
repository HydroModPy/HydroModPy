from __future__ import annotations

import json
from pathlib import Path

import pytest

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
                '[workflow]\nmode = "simulation"',
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
        / "tests"
        / "regression"
        / "fixtures"
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


def test_launcher_simulation_mf6_precomputed_mesh_input_config_uses_runtime_mesh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_config = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "regression"
        / "fixtures"
        / "projects"
        / "launcher_simulation"
        / "run_fast_mf6_precomputed_mesh_input.toml"
    )

    payload = load_toml_with_base_config(example_config)

    assert payload["mesh_input"]["mesh_path"] == "results_stable/mesh/mesh_catchment.msh"
    assert payload["mesh_input"]["bundle_dir"] == "results_stable/mesh/mesh_catchment_bundle"
    assert "planar" not in payload["modflow6"]["sgrid"]
    assert payload["modflow6"]["sgrid"]["vertical"]["nlay"] == 2
    assert "postprocess" not in payload
    monkeypatch.setenv("HYDROMODPY_WORKSPACE", str(tmp_path))
    cfg = HydroModPyConfig.from_toml(example_config)
    assert list(cfg.simulation.process[0].solvers) == ["modflow6"]


def test_launcher_simulation_mf6_mesh_catchment_config_embeds_mesh_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_config = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "regression"
        / "fixtures"
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
    assert payload["flow"]["param"]["K"]["field"]["value"] == "1e-5 m/s"
    assert payload["flow"]["param"]["Sy"]["field"]["value"] == "0.12 -"
    assert payload["data"]["recharge"]["sources"][0]["freq"] == "10D"
    assert "postprocess" not in payload
    assert payload["analysis"]["capability_gallery"]["enabled"] is True
    assert payload["analysis"]["capability_gallery"]["case_slug"] == "modflow6_gmsh_mesh_catchment"

    monkeypatch.setenv("HYDROMODPY_WORKSPACE", str(tmp_path))
    cfg = HydroModPyConfig.from_toml(example_config)
    assert cfg.mesh_catchment is not None


def test_data_overview_example_declares_overview_workflow_and_report_section() -> None:
    example_config = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "projects"
        / "04_data_overview"
        / "project.toml"
    )

    cfg = HydroModPyConfig.from_toml(example_config)

    assert cfg.workflow.mode == "overview"
    assert cfg.overview is not None
    assert cfg.overview.date_start == "2019-01-01"
    assert cfg.overview.date_end == "2025-12-31"
    assert cfg.overview.panels.map_dem is True
    assert cfg.overview.panels.timeseries_piezometry is False
    assert cfg.overview.panels.climatic_summary is False


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
                f'data_dir = "{tmp_path / "data"}"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                "",
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
                "",
                "[geographic]",
                'source_mode = "synthetic"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.calibration is None


def test_hydromodpy_config_rejects_unknown_flow_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "unknown_flow.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
                "",
                "[flow]",
                "typo_runtime = true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"Unknown TOML key\(s\) in \[flow\]"):
        HydroModPyConfig.from_toml(config_path)


def test_hydromodpy_config_from_dict_uses_toml_normalization(tmp_path: Path) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    cfg = HydroModPyConfig.from_dict(
        {
            "workflow": {"mode": "simulation"},
            "workspace": {"root": str(tmp_path), "project_root": ""},
            "geographic": {"catch_def": "dem", "dem_init_path": "dem.tif"},
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


def test_hydromodpy_config_from_json_uses_toml_normalization(tmp_path: Path) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()
    payload = {
        "workflow": {"mode": "simulation"},
        "workspace": {"root": str(tmp_path), "project_root": str(tmp_path)},
        "geographic": {"catch_def": "dem", "dem_init_path": "dem.tif"},
    }

    cfg = HydroModPyConfig.from_json(json.dumps(payload), base_dir=tmp_path)

    assert cfg.geographic.dem_init_path == dem_path.resolve()


def test_hydromodpy_config_rejects_unknown_workflow(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown-workflow"):
        HydroModPyConfig.from_dict(
            {
                "workflow": {"mode": "unknown-workflow"},
                "workspace": {"root": str(tmp_path)},
                "geographic": {"source_mode": "synthetic"},
            },
            base_dir=tmp_path,
        )
