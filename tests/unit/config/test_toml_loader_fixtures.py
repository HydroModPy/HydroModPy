from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

from ._test_toml_loader_builders import (
    example_project_config,
    simulation_regression_fixture,
)


def test_simulation_regression_example_config_inheritance_keeps_only_relevant_data_types() -> None:
    example_config = simulation_regression_fixture("run_fast_mf6.toml")

    payload = load_toml_with_base_config(example_config)

    assert payload["flow"]["active_bc"] == ["ocean", "drainage"]
    assert payload["data"]["types"] == ["recharge"]
    assert "hydrography" not in payload["data"]
    assert payload["data"]["oceanic"]["sources"][0]["source"] == "custom"
    assert payload["data"]["recharge"]["sources"][0]["source"] == "synthetic"


def test_simulation_regression_mf6_precomputed_mesh_input_config_uses_runtime_mesh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_config = simulation_regression_fixture("run_fast_mf6_precomputed_mesh_input.toml")

    payload = load_toml_with_base_config(example_config)

    assert payload["mesh_input"]["mesh_path"] == "results_stable/mesh/mesh_catchment.msh"
    assert payload["mesh_input"]["bundle_dir"] == "results_stable/mesh/mesh_catchment_bundle"
    assert "planar" not in payload["modflow6"]["sgrid"]
    assert payload["modflow6"]["sgrid"]["vertical"]["nlay"] == 2
    assert "postprocess" not in payload
    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    cfg = HydroModPyConfig.from_toml(example_config)
    assert list(cfg.simulation.process[0].solvers) == ["modflow6"]


def test_simulation_regression_mf6_mesh_catchment_config_embeds_mesh_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_config = simulation_regression_fixture("run_fast_mf6_mesh_catchment.toml")

    payload = load_toml_with_base_config(example_config)

    assert payload["mesh_catchment"]["constraints_mode"] == "geology_rivers"
    assert payload["simulation"]["name"] == "example12_fast_mf6_mesh_catchment"
    assert payload["simulation"]["process"][0]["solvers"] == ["modflow6"]
    assert payload["simulation"]["process"][1]["solvers"] == ["modflow6"]
    assert payload["simulation"]["time"]["step_value"] == "10 day"
    assert payload["flow"]["first_period_steady"] is False
    assert payload["flow"]["ic"]["type"] == "top"
    assert payload["flow"]["param"]["K"]["field"]["value"] == "1e-5 m/s"
    assert payload["flow"]["param"]["Sy"]["field"]["value"] == "0.12 -"
    assert payload["data"]["recharge"]["sources"][0]["freq"] == "10D"
    assert "postprocess" not in payload
    assert payload["analysis"]["capability_gallery"]["enabled"] is True
    assert payload["analysis"]["capability_gallery"]["case_slug"] == "modflow6_gmsh_mesh_catchment"

    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    cfg = HydroModPyConfig.from_toml(example_config)
    assert cfg.mesh_catchment is not None
    assert cfg.flow.first_period_steady is False


def test_data_overview_example_declares_overview_workflow_and_report_section() -> None:
    example_config = example_project_config("04_data_overview", "project.toml")

    cfg = HydroModPyConfig.from_toml(example_config)

    assert cfg.workflow.mode == "overview"
    assert cfg.overview is not None
    assert cfg.overview.date_start == "2019-01-01"
    assert cfg.overview.date_end == "2025-12-31"
    assert cfg.overview.panels.map_dem is True
    assert cfg.overview.panels.timeseries_piezometry is False
    assert cfg.overview.panels.climatic_summary is False
