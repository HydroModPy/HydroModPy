from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle import (
    resolve_default_catchment_mesh_bundle_dir,
)
from launchers.model_calibration.config import ModelCalibrationConfig
from launchers.model_calibration.launcher import ModelCalibrationLauncher
from launchers.model_calibration.runtime import (
    IterationRecord,
    ModelCalibrationObjectiveEvaluator,
    append_iteration_record,
    select_candidate_outputs,
)
from launchers.model_calibration.output_selection import (
    canonicalize_run_outputs,
    prepare_output_selectors,
)
from launchers.model_calibration.property_arrays import build_property_array_set
from launchers.model_calibration.templates import render_model_calibration_template
from validation_cases.shared.runtime import (
    _dump_toml,
    _merge_toml_payloads,
    _read_toml,
)


def _load_launchers_main_module():
    module_path = Path(__file__).resolve().parents[3] / "launchers" / "__main__.py"
    spec = importlib.util.spec_from_file_location(
        "launchers_main_model_calibration_test_module",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_minimal_simulation_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[workspace]",
                'project_root = "project/demo_case"',
                "",
                "[simulation]",
                'run_id = "demo_flow_run"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["modflow6"]',
                "",
                "[flow]",
                'param_list = ["K", "Sy"]',
                "",
                "[flow.param.K.field]",
                'kind = "homogeneous"',
                "",
                "[flow.param.K.field_homogeneous]",
                'value = "5e-5 m/s"',
                "",
                "[flow.param.Sy.field]",
                'kind = "homogeneous"',
                "",
                "[flow.param.Sy.field_homogeneous]",
                'value = "0.02 -"',
                "",
                "[display]",
                "enabled = true",
                "show = true",
                "save = false",
                "",
                "[postprocess]",
                "enabled = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_bundle_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _write_minimal_calibration_bundle(bundle_dir: Path) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mesh_2d.msh").write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "files": {"mesh": "mesh_2d.msh"},
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_bundle_csv(
        bundle_dir / "nodes.csv",
        "node_id,x,y,z_top,z_bottom",
        [
            "0,0.0,0.0,10.0,5.0",
            "1,1.0,0.0,10.0,5.0",
            "2,1.0,1.0,10.0,5.0",
            "3,0.0,1.0,10.0,5.0",
        ],
    )
    _write_bundle_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
        [
            "0,triangle,0,1,2,,0.666667,0.333333,0.5,10.0,10.0,5.0,5.0,1,granite,1.0e-5,0.10",
            "1,triangle,0,2,3,,0.333333,0.666667,0.5,11.0,11.0,4.0,4.0,2,schist,2.0e-5,0.15",
        ],
    )
    _write_bundle_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
        [
            "0,0,1,0,,1.0,boundary,false,granite,",
            "1,1,2,0,,1.0,boundary,false,granite,",
            "2,0,2,0,1,1.414214,internal,false,granite,schist",
            "3,2,3,1,,1.0,boundary,false,schist,",
            "4,0,3,1,,1.0,boundary,false,schist,",
        ],
    )
    _write_bundle_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        [
            "0,granite,1.0",
            "1,schist,1.0",
        ],
    )
    return bundle_dir


def _write_mesh_summary(
    path: Path,
    *,
    bundle_dir: Path,
    mesh_path: Path | None = None,
    relative_bundle_dir: bool = False,
) -> Path:
    payload: dict[str, object] = {
        "output_exchange_bundle_dir": (
            bundle_dir.name if relative_bundle_dir else str(bundle_dir)
        )
    }
    if mesh_path is not None:
        payload["output_mesh"] = str(mesh_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_minimal_model_calibration_config(
    path: Path,
    *,
    include_observed_values: bool = False,
    global_method: str = "simplex",
    rerun_model_distribution_with_outputs: bool = False,
    model_distribution_max_reruns: int = 10,
    model_distribution_rerun_selection: str = "representative",
    persist_iteration_history: bool = True,
    persist_iteration_detail_level: str = "minimal",
    persist_calibration_report: bool = True,
    resume_existing_session: bool = True,
    reuse_persisted_iterations: bool = True,
    objective_mapping_enabled: bool = False,
    objective_mapping_additional_runs: int = 0,
    objective_mapping_interpolation: str = "idw",
) -> None:
    head_observations = (
        ['observed_values = [10.0, 14.0]'] if include_observed_values else []
    )
    flux_observations = (
        ['observed_values = [4.0, 8.0]'] if include_observed_values else []
    )
    method_lines_by_name = {
        "simplex": [
            "[calibration_method.simplex]",
            "max_iter = 50",
        ],
        "random_search": [
            "[calibration_method.random_search]",
            "n_samples = 2",
            "seed = 42",
        ],
        "da_mh_gp": [
            "[calibration_method.da_mh_gp]",
            "sigma_noise = 0.1",
        ],
    }
    method_lines = method_lines_by_name[str(global_method)]
    objective_mapping_lines = (
        [
            "",
            "[model_calibration.objective_mapping]",
            f"enabled = {str(objective_mapping_enabled).lower()}",
            'axes = ["K_global_factor", "Sy_global"]',
            f"additional_runs = {objective_mapping_additional_runs}",
            'sampling = "adaptive"',
            f'interpolation = "{objective_mapping_interpolation}"',
            "grid_size = 12",
            "candidate_pool_size = 32",
            "idw_power = 2.0",
            "random_seed = 7",
            "include_block_contributions = true",
            'output_points_csv = "objective_mapping_points.csv"',
            'output_grid_json = "objective_mapping_grid.json"',
            'output_figure = "objective_mapping.png"',
        ]
        if objective_mapping_enabled
        else []
    )
    path.write_text(
        "\n".join(
            [
                "[model_calibration]",
                'simulation_config = "run_flow_reference.toml"',
                'calibration_id = "calib_case_01"',
                "disable_display = true",
                "disable_postprocess = true",
                "rerun_best_with_outputs = true",
                "persist_model_distribution = true",
                (
                    "rerun_model_distribution_with_outputs = "
                    f"{str(rerun_model_distribution_with_outputs).lower()}"
                ),
                f"model_distribution_max_reruns = {model_distribution_max_reruns}",
                (
                    "model_distribution_rerun_selection = "
                    f'"{model_distribution_rerun_selection}"'
                ),
                f"persist_iteration_history = {str(persist_iteration_history).lower()}",
                f'persist_iteration_detail_level = "{persist_iteration_detail_level}"',
                f"persist_calibration_report = {str(persist_calibration_report).lower()}",
                f"resume_existing_session = {str(resume_existing_session).lower()}",
                (
                    "reuse_persisted_iterations = "
                    f"{str(reuse_persisted_iterations).lower()}"
                ),
                *objective_mapping_lines,
                "",
                "[calibration]",
                'objective_metric = "rmse"',
                f'global_method = "{global_method}"',
                "",
                "[objective]",
                'transform = "identity"',
                "",
                *method_lines,
                "",
                "[bounds]",
                "K_global_factor = [0.1, 10.0]",
                "Sy_global = [0.01, 0.30]",
                "",
                "[[model_calibration.parameter]]",
                'name = "K_global_factor"',
                'property = "K"',
                'target = "flow.param.K.field_homogeneous.value"',
                'mode = "scale"',
                'parameterization = "global_factor"',
                "",
                "[[model_calibration.parameter]]",
                'name = "Sy_global"',
                'property = "Sy"',
                'target = "flow.param.Sy.field_homogeneous.value"',
                'mode = "replace"',
                'parameterization = "global_value"',
                "",
                "[[model_calibration.output]]",
                'name = "pz_01"',
                'variable = "watertable_elevation"',
                'source = "runtime"',
                'support = "point"',
                "x = 1.0",
                "y = 2.0",
                'time = "all"',
                *head_observations,
                "",
                "[[model_calibration.output]]",
                'name = "q_outlet_lowflow_mean"',
                'variable = "outlet_discharge"',
                'source = "runtime"',
                'support = "boundary"',
                'boundary_id = "east_side"',
                'time_window = ["2020-08-01", "2020-09-30"]',
                'time_reducer = "mean"',
                *flux_observations,
                "",
                "[[model_calibration.objective_block]]",
                'name = "heads"',
                'metric = "rmse"',
                "weight = 1.0",
                'uses_outputs = ["pz_01"]',
                "normalize_cost = true",
                "",
                "[[model_calibration.objective_block]]",
                'name = "flux"',
                'metric = "rmse"',
                "weight = 1.0",
                'uses_outputs = ["q_outlet_lowflow_mean"]',
                "normalize_cost = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_validation_dupuit_modflow6_simulation_config(path: Path, *, project_root: Path) -> None:
    case_dir = (
        Path(__file__).resolve().parents[3]
        / "validation_cases"
        / "analytical"
        / "steady"
        / "dupuit_fixed_head_1d"
    )
    payload = _merge_toml_payloads(
        _read_toml(case_dir / "config_common.toml"),
        _read_toml(case_dir / "config_modflow6.toml"),
    )
    payload.setdefault("workspace", {})["project_root"] = str(project_root)
    payload.setdefault("simulation", {})["run_id"] = "dupuit_fixed_head_1d_runtime_prepare"
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def _write_dupuit_runtime_prepare_calibration_config(path: Path, *, simulation_config_name: str) -> None:
    path.write_text(
        "\n".join(
            [
                "[model_calibration]",
                f'simulation_config = "{simulation_config_name}"',
                'calibration_id = "dupuit_runtime_prepare"',
                "disable_display = true",
                "disable_postprocess = true",
                "rerun_best_with_outputs = false",
                "persist_model_distribution = false",
                "persist_iteration_history = false",
                "persist_calibration_report = false",
                "",
                "[[model_calibration.parameter]]",
                'name = "K_global_factor"',
                'property = "K"',
                'target = "flow.param.K.field_homogeneous.value"',
                'mode = "scale"',
                'parameterization = "global_factor"',
                "",
                "[[model_calibration.output]]",
                'name = "q_east"',
                'variable = "outlet_discharge"',
                'source = "runtime"',
                'support = "boundary"',
                'boundary_id = "east_side"',
                'time = "all"',
                "observed_values = [4.6875e-4]",
                "",
                "[[model_calibration.objective_block]]",
                'name = "flux"',
                'metric = "rmse"',
                "weight = 1.0",
                'uses_outputs = ["q_east"]',
                "normalize_cost = true",
                "",
                "[calibration]",
                'objective_metric = "rmse"',
                'global_method = "random_search"',
                "",
                "[objective]",
                'transform = "identity"',
                "",
                "[calibration_method.random_search]",
                "n_samples = 1",
                "seed = 7",
                "",
                "[bounds]",
                "K_global_factor = [0.5, 1.5]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_runtime_zone_supported_simulation_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[workspace]",
                'project_root = "project/demo_case"',
                "",
                "[simulation]",
                'run_id = "demo_flow_zones"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["modflow6"]',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
                "",
                "[geographic.synthetic]",
                'case_id = "demo_zones"',
                "",
                "[geographic.synthetic.grid]",
                'length_x = "400.0 m"',
                'length_y = "50.0 m"',
                "nx = 40",
                "ny = 5",
                "",
                "[geographic.synthetic.topography]",
                'kind = "flat"',
                "base_elevation = 20.0",
                "",
                "[domain]",
                'zone_ids = ["k_bands"]',
                "",
                "[domain.depth_model]",
                'type = "constant_thickness"',
                'thickness = "20.0 m"',
                "",
                "[domain.supports.k_bands]",
                'provider = "generated_bands"',
                'axis = "x"',
                'coordinate_mode = "relative"',
                "breaks = [0.5]",
                'labels = ["west_zone", "east_zone"]',
                "",
                "[flow]",
                'flow_regime = "steady"',
                'active_sinks_sources = []',
                'active_bc = ["west_side", "east_side"]',
                'param_list = ["K"]',
                "",
                "[flow.param.K.field]",
                'id = "K"',
                'kind = "heterogeneous"',
                "",
                "[flow.param.K.field_heterogeneous]",
                'values_source = "inline"',
                'field_spatial_id = "k_bands"',
                'values = { west_zone = "2e-4 m/s", east_zone = "5e-5 m/s" }',
                "",
                "[flow.ic]",
                'type = "custom"',
                'value = "7.5 m"',
                "",
                "[flow.bc.dirichlet.west_side]",
                'type = "dirichlet"',
                'value = "10.0 m"',
                "",
                "[flow.bc.dirichlet.east_side]",
                'type = "dirichlet"',
                'value = "5.0 m"',
                "",
                "[modflow6.runtime]",
                'mf6_ims_complexity = "SIMPLE"',
                'mf_verbose = false',
                "",
                "[modflow6.process_specific]",
                "vka = 1.0",
                "",
                "[modflow6.sgrid.planar]",
                'mode = "resample_to_shape"',
                "nx = 40",
                "ny = 5",
                'resampling = "nearest"',
                "",
                "[modflow6.sgrid.vertical]",
                "nlay = 1",
                "",
                "[display]",
                "enabled = false",
                "",
                "[postprocess]",
                "enabled = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_runtime_zone_calibration_config(path: Path, *, simulation_config_name: str) -> None:
    path.write_text(
        "\n".join(
            [
                "[model_calibration]",
                f'simulation_config = "{simulation_config_name}"',
                'calibration_id = "runtime_zone_calib"',
                "disable_display = true",
                "disable_postprocess = true",
                "persist_iteration_history = false",
                "persist_calibration_report = false",
                "persist_model_distribution = false",
                "",
                "[[model_calibration.parameter]]",
                'name = "K_west"',
                'property = "K"',
                'target = "flow.param.K.values_by_key.west_zone"',
                'mode = "replace"',
                'parameterization = "lithology_value"',
                "",
                "[[model_calibration.output]]",
                'name = "q_east"',
                'variable = "outlet_discharge"',
                'source = "runtime"',
                'support = "boundary"',
                'boundary_id = "east_side"',
                'time = "all"',
                "observed_values = [1.0]",
                "",
                "[[model_calibration.objective_block]]",
                'name = "flux"',
                'metric = "rmse"',
                "weight = 1.0",
                'uses_outputs = ["q_east"]',
                "normalize_cost = true",
                "",
                "[calibration]",
                'objective_metric = "rmse"',
                'global_method = "random_search"',
                "",
                "[objective]",
                'transform = "identity"',
                "",
                "[calibration_method.random_search]",
                "n_samples = 1",
                "seed = 7",
                "",
                "[bounds]",
                "K_west = [1.0e-4, 5.0e-4]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_model_calibration_config_resolves_simulation_path_and_core_settings(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_model_calibration_config(config_path)

    cfg = ModelCalibrationConfig.from_toml(
        raw_toml={
            "model_calibration": {
                "simulation_config": "run_flow_reference.toml",
                "calibration_id": "calib_case_01",
                "disable_display": True,
                "disable_postprocess": True,
                "rerun_best_with_outputs": True,
                "persist_iteration_history": True,
                "persist_iteration_detail_level": "minimal",
                "parameter": [
                        {
                            "name": "K_global_factor",
                            "property": "K",
                            "target": "flow.param.K.field_homogeneous.value",
                            "mode": "scale",
                            "parameterization": "global_factor",
                        },
                        {
                            "name": "Sy_global",
                            "property": "Sy",
                            "target": "flow.param.Sy.field_homogeneous.value",
                            "mode": "replace",
                            "parameterization": "global_value",
                        },
                ],
                "output": [
                    {
                        "name": "pz_01",
                        "variable": "watertable_elevation",
                        "source": "runtime",
                        "support": "point",
                        "x": 1.0,
                        "y": 2.0,
                        "time": "all",
                    },
                    {
                        "name": "q_outlet_lowflow_mean",
                        "variable": "outlet_discharge",
                        "source": "runtime",
                        "support": "boundary",
                        "boundary_id": "east_side",
                        "time_window": ["2020-08-01", "2020-09-30"],
                        "time_reducer": "mean",
                    },
                ],
                "objective_block": [
                    {
                        "name": "heads",
                        "metric": "rmse",
                        "weight": 1.0,
                        "uses_outputs": ["pz_01"],
                    },
                    {
                        "name": "flux",
                        "metric": "rmse",
                        "weight": 1.0,
                        "uses_outputs": ["q_outlet_lowflow_mean"],
                    },
                ],
            },
                "calibration": {
                    "objective_metric": "rmse",
                    "global_method": "simplex",
                },
                "objective": {"transform": "identity"},
                "calibration_method": {"simplex": {"max_iter": 50}},
                "bounds": {
                    "K_global_factor": [0.1, 10.0],
                    "Sy_global": [0.01, 0.30],
            },
        },
        base_dir=tmp_path,
    )

    assert cfg.simulation_config_path == (tmp_path / "run_flow_reference.toml").resolve()
    assert cfg.parameter_names == ("K_global_factor", "Sy_global")
    assert cfg.output_names == ("pz_01", "q_outlet_lowflow_mean")
    assert cfg.model_calibration.output[0].reducer == "weighted_interpolation"
    assert cfg.model_calibration.output[1].reducer == "sum"
    assert cfg.model_calibration.persist_model_distribution is True
    assert cfg.model_calibration.rerun_model_distribution_with_outputs is False
    assert cfg.model_calibration.model_distribution_max_reruns == 10
    assert (
        cfg.model_calibration.model_distribution_rerun_selection
        == "representative"
    )
    assert cfg.model_calibration.persist_calibration_report is True
    assert cfg.model_calibration.resume_existing_session is True
    assert cfg.model_calibration.reuse_persisted_iterations is True
    assert cfg.model_calibration.objective_mapping.enabled is False

    core_settings = cfg.resolve_core_settings()
    assert core_settings["method"] == "simplex"
    assert core_settings["parameter_names"] == ("K_global_factor", "Sy_global")


def test_model_calibration_launcher_returns_scaffold_summary(tmp_path: Path) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(config_path)

    summary = ModelCalibrationLauncher(config_path).run()

    assert summary["mode"] == "model_calibration"
    assert summary["status"] == "prepared"
    assert summary["primary_solver"] == "modflow6"
    assert summary["supported_v1_backend"] is True
    assert summary["n_parameters"] == 2
    assert summary["n_outputs"] == 2
    assert summary["n_prepared_output_selectors"] == 2
    assert summary["n_objective_blocks"] == 2
    assert summary["parameter_names"] == ["K_global_factor", "Sy_global"]
    assert summary["objective_block_names"] == ["heads", "flux"]
    assert summary["calibration_root"].endswith(
        str(Path("project/demo_case/results_calibration/calib_case_01"))
    )
    manifest_path = Path(summary["session_manifest_path"])
    history_path = Path(summary["iteration_history_path"])
    assert manifest_path.is_file()
    assert history_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "prepared"
    assert manifest["iteration_count"] == 0
    assert manifest["persist_iteration_history"] is True
    assert manifest["persist_iteration_detail_level"] == "minimal"
    assert manifest["persist_calibration_report"] is True
    assert manifest["resume_existing_session"] is True
    assert manifest["reuse_persisted_iterations"] is True
    assert manifest["persisted_iteration_reuse_allowed"] is True
    assert manifest["primary_solver"] == "modflow6"
    assert isinstance(manifest["session_contract_signature"], str)
    assert len(manifest["session_contract_signature"]) == 64


def test_model_calibration_template_contains_expected_sections() -> None:
    content = render_model_calibration_template()

    assert "[model_calibration]" in content
    assert "[[model_calibration.parameter]]" in content
    assert "[[model_calibration.output]]" in content
    assert "[[model_calibration.objective_block]]" in content
    assert 'reducer = "weighted_interpolation"' in content
    assert "persist_calibration_report = true" in content
    assert "resume_existing_session = true" in content
    assert "reuse_persisted_iterations = true" in content


def test_append_iteration_record_writes_minimal_jsonl(tmp_path: Path) -> None:
    history_path = tmp_path / "iteration_history.jsonl"

    append_iteration_record(
        history_path=history_path,
        record=IterationRecord(
            iteration_id="iter_0001",
            params_vector=(1.0, 0.2),
            params_named={"K_global_factor": 1.0, "Sy_global": 0.2},
            objective_total=0.42,
            block_costs={"heads": 0.30, "flux": 0.12},
            status="ok",
            failure_reason=None,
        ),
    )

    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["iteration_id"] == "iter_0001"
    assert payload["params_vector"] == [1.0, 0.2]
    assert payload["params_named"] == {"K_global_factor": 1.0, "Sy_global": 0.2}
    assert payload["objective_total"] == 0.42
    assert payload["block_costs"] == {"heads": 0.3, "flux": 0.12}
    assert payload["status"] == "ok"
    assert payload["failure_reason"] is None
    assert "block_details" not in payload


def test_append_iteration_record_writes_diagnostic_jsonl(tmp_path: Path) -> None:
    history_path = tmp_path / "iteration_history.jsonl"

    append_iteration_record(
        history_path=history_path,
        detail_level="diagnostic",
        record=IterationRecord(
            iteration_id="iter_0001",
            params_vector=(1.0, 0.2),
            params_named={"K_global_factor": 1.0, "Sy_global": 0.2},
            objective_total=0.42,
            objective_score=-0.42,
            block_costs={"heads": 0.30},
            block_details=(
                {
                    "name": "heads",
                    "metric": "rmse",
                    "raw_cost": 0.30,
                    "normalized_cost": 0.30,
                },
            ),
            status="objective_evaluated",
            candidate_run_id="calib_case_01__iter_0001",
            candidate_config_path="runtime_candidates/iter_0001/candidate.toml",
        ),
    )

    payload = json.loads(history_path.read_text(encoding="utf-8"))
    assert payload["objective_score"] == -0.42
    assert payload["block_details"][0]["name"] == "heads"
    assert payload["candidate_run_id"] == "calib_case_01__iter_0001"
    assert "objective_metadata" not in payload


def test_model_calibration_select_outputs_can_use_variable_supports(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_model_calibration_config(config_path)
    cfg = ModelCalibrationConfig.from_toml(
        load_toml_with_base_config(config_path),
        base_dir=tmp_path,
    )

    selected = select_candidate_outputs(
        cfg=cfg,
        run_state={
            "outputs": {
                "watertable_elevation": {
                    "x": [0.0, 2.0],
                    "y": [0.0, 0.0],
                    "values": [10.0, 20.0],
                },
                "outlet_discharge": {
                    "east_side": [1.5, 2.5],
                },
            },
        },
    )

    assert selected["pz_01"] == (pytest.approx(15.0),)
    assert selected["q_outlet_lowflow_mean"] == (pytest.approx(4.0),)


def test_model_calibration_canonicalizes_run_outputs() -> None:
    bundle = canonicalize_run_outputs(
        {
            "calibration_outputs": {"pz_01": [10.0]},
            "outputs": {"watertable_elevation": [9.0]},
        }
    )

    assert bundle.get("pz_01") == [10.0]
    assert bundle.get("watertable_elevation") == [9.0]
    assert bundle.variables["pz_01"].source_key == "calibration_outputs"


def test_model_calibration_canonicalizes_runtime_solver_model_outputs() -> None:
    model = SimpleNamespace(
        runtime_mesh_support=SimpleNamespace(
            cell_centroid_x_m=np.asarray([0.0, 2.0], dtype=float),
            cell_centroid_y_m=np.asarray([2.0, 2.0], dtype=float),
        ),
        dict_watertable_elevation={
            "2020-08-15": np.asarray([10.0, 20.0], dtype=float),
            "2020-09-15": np.asarray([14.0, 18.0], dtype=float),
        },
        dict_outlet_discharge_east_side_m3_s={
            "2020-08-15": np.asarray([4.0], dtype=float),
            "2020-09-15": np.asarray([8.0], dtype=float),
        },
    )
    run_state = SimpleNamespace(
        execution=SimpleNamespace(models_by_run_id={"flow_main": model})
    )

    bundle = canonicalize_run_outputs(run_state)

    watertable = bundle.get("watertable_elevation")
    assert list(watertable.keys()) == ["2020-08-15", "2020-09-15"]
    assert np.asarray(watertable["2020-08-15"]["coordinates"]).shape == (2, 2)
    assert watertable["2020-08-15"]["values"].tolist() == pytest.approx(
        [10.0, 20.0]
    )
    assert bundle.get("outlet_discharge")["2020-08-15"]["east_side"] == (
        pytest.approx(4.0),
    )
    assert bundle.variables["watertable_elevation"].source_key == (
        "execution.models_by_run_id[flow_main].runtime_attribute"
    )


def test_model_calibration_selects_outputs_from_runtime_solver_models(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_model_calibration_config(config_path)
    cfg = ModelCalibrationConfig.from_toml(
        load_toml_with_base_config(config_path),
        base_dir=tmp_path,
    )
    run_state = SimpleNamespace(
        execution=SimpleNamespace(
            models_by_run_id={
                "flow_main": SimpleNamespace(
                    runtime_mesh_support=SimpleNamespace(
                        cell_centroid_x_m=np.asarray([0.0, 2.0], dtype=float),
                        cell_centroid_y_m=np.asarray([2.0, 2.0], dtype=float),
                    ),
                    dict_watertable_elevation={
                        "2020-08-15": np.asarray([10.0, 20.0], dtype=float),
                        "2020-09-15": np.asarray([14.0, 18.0], dtype=float),
                    },
                    dict_outlet_discharge_east_side_m3_s={
                        "2020-08-15": np.asarray([4.0], dtype=float),
                        "2020-09-15": np.asarray([8.0], dtype=float),
                    },
                )
            }
        )
    )

    selected = select_candidate_outputs(
        cfg=cfg,
        run_state=run_state,
    )

    assert selected["pz_01"] == (pytest.approx(15.0), pytest.approx(16.0))
    assert selected["q_outlet_lowflow_mean"] == (pytest.approx(6.0),)


def test_model_calibration_selects_outputs_from_solver_postprocess_npy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_model_calibration_config(config_path)
    cfg = ModelCalibrationConfig.from_toml(
        load_toml_with_base_config(config_path),
        base_dir=tmp_path,
    )

    model_root = tmp_path / "flow_main"
    postprocess_dir = model_root / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        postprocess_dir / "watertable_elevation.npy",
        {
            "2020-08-15": np.asarray([10.0, 20.0], dtype=float),
            "2020-09-15": np.asarray([14.0, 18.0], dtype=float),
        },
        allow_pickle=True,
    )
    np.save(
        postprocess_dir / "outlet_discharge_east_side_m3_s.npy",
        {
            "2020-08-15": np.asarray([4.0], dtype=float),
            "2020-09-15": np.asarray([8.0], dtype=float),
        },
        allow_pickle=True,
    )

    run_state = SimpleNamespace(
        execution=SimpleNamespace(
            models_by_run_id={
                "flow_main": SimpleNamespace(
                    full_path=str(model_root),
                    runtime_mesh_support=SimpleNamespace(
                        cell_centroid_x_m=np.asarray([0.0, 2.0], dtype=float),
                        cell_centroid_y_m=np.asarray([2.0, 2.0], dtype=float),
                    ),
                )
            }
        )
    )

    selected = select_candidate_outputs(
        cfg=cfg,
        run_state=run_state,
    )

    assert selected["pz_01"] == (pytest.approx(15.0), pytest.approx(16.0))
    assert selected["q_outlet_lowflow_mean"] == (pytest.approx(6.0),)


def test_model_calibration_selects_outputs_from_solver_native_mesh_npz(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_model_calibration_config(config_path)
    cfg = ModelCalibrationConfig.from_toml(
        load_toml_with_base_config(config_path),
        base_dir=tmp_path,
    )

    model_root = tmp_path / "flow_main_npz"
    mesh_dir = model_root / "_postprocess" / "_mesh"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        mesh_dir / "flow_watertable_elevation.npz",
        time_index=np.asarray(["2020-08-15", "2020-09-15"]),
        cell_ids=np.asarray([0, 1], dtype=int),
        values=np.asarray([[10.0, 20.0], [14.0, 18.0]], dtype=float),
    )
    np.save(
        model_root / "_postprocess" / "outlet_discharge_east_side_m3_s.npy",
        {
            "2020-08-15": np.asarray([4.0], dtype=float),
            "2020-09-15": np.asarray([8.0], dtype=float),
        },
        allow_pickle=True,
    )

    run_state = SimpleNamespace(
        execution=SimpleNamespace(
            models_by_run_id={
                "flow_main": SimpleNamespace(
                    full_path=str(model_root),
                    runtime_mesh_support=SimpleNamespace(
                        cell_centroid_x_m=np.asarray([0.0, 2.0], dtype=float),
                        cell_centroid_y_m=np.asarray([2.0, 2.0], dtype=float),
                    ),
                )
            }
        )
    )

    selected = select_candidate_outputs(
        cfg=cfg,
        run_state=run_state,
    )

    assert selected["pz_01"] == (pytest.approx(15.0), pytest.approx(16.0))
    assert selected["q_outlet_lowflow_mean"] == (pytest.approx(6.0),)


def test_model_calibration_prepares_output_selectors(tmp_path: Path) -> None:
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_model_calibration_config(config_path)
    cfg = ModelCalibrationConfig.from_toml(
        load_toml_with_base_config(config_path),
        base_dir=tmp_path,
    )

    selectors = prepare_output_selectors(cfg)

    assert [selector.name for selector in selectors] == [
        "pz_01",
        "q_outlet_lowflow_mean",
    ]
    assert selectors[0].variable_keys == ("watertable_elevation",)
    assert selectors[1].variable_keys == (
        "outlet_discharge",
        "outlet_discharge_east_side_m3_s",
    )


def test_model_calibration_actualize_candidate_writes_override_config(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(config_path)

    launcher = ModelCalibrationLauncher(config_path)
    request = launcher.actualize_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
    )

    assert request.iteration_id == "iter_0001"
    assert request.candidate_run_id == "calib_case_01__iter_0001"
    assert request.candidate_config_path.is_file()
    assert request.params_named == {"K_global_factor": 2.0, "Sy_global": 0.15}
    assert request.property_array_error is None
    assert request.property_array_summary is not None
    assert request.property_array_summary["properties"]["K"]["stats"]["count"] == 1
    assert request.property_array_summary["properties"]["K"]["stats"]["mean"] == (
        pytest.approx(1.0e-4)
    )
    assert request.property_array_summary["properties"]["Sy"]["stats"]["mean"] == (
        pytest.approx(0.15)
    )

    merged = load_toml_with_base_config(request.candidate_config_path)
    assert merged["simulation"]["run_id"] == "calib_case_01__iter_0001"
    assert merged["flow"]["param"]["K"]["field_homogeneous"]["value"] == "0.0001 m/s"
    assert merged["flow"]["param"]["Sy"]["field_homogeneous"]["value"] == "0.15 -"
    assert merged["display"]["enabled"] is False
    assert merged["display"]["show"] is False
    assert merged["postprocess"]["enabled"] is False


def test_model_calibration_builds_global_property_arrays(tmp_path: Path) -> None:
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_model_calibration_config(config_path)
    cfg = ModelCalibrationConfig.from_toml(
        load_toml_with_base_config(config_path),
        base_dir=tmp_path,
    )

    property_set = build_property_array_set(
        cfg=cfg,
        params={"K_global_factor": 2.0, "Sy_global": 0.15},
        base_property_arrays={
            "K": [5.0e-5, 1.0e-4, 2.0e-4],
            "Sy": [0.02, 0.03, 0.04],
        },
    )

    assert property_set.get("K").values.tolist() == pytest.approx(
        [1.0e-4, 2.0e-4, 4.0e-4]
    )
    assert property_set.get("Sy").values.tolist() == pytest.approx(
        [0.15, 0.15, 0.15]
    )
    assert property_set.get("K").metadata["K_global_factor"]["mode"] == "scale"


def test_model_calibration_builds_lithology_property_arrays(tmp_path: Path) -> None:
    raw_toml = {
        "model_calibration": {
            "simulation_config": "run_flow_reference.toml",
            "calibration_id": "calib_case_01",
            "parameter": [
                {
                    "name": "K_alluvium",
                    "property": "K",
                    "target": "flow.param.K.values_by_key.alluvium",
                    "mode": "replace",
                    "parameterization": "lithology_value",
                },
                {
                    "name": "K_basement",
                    "property": "K",
                    "target": "flow.param.K.values_by_key.basement",
                    "mode": "scale",
                    "parameterization": "lithology_value",
                    "lithology_key": "basement",
                },
            ],
            "output": [
                {
                    "name": "pz_01",
                    "variable": "watertable_elevation",
                    "support": "point",
                    "x": 1.0,
                    "y": 2.0,
                },
            ],
            "objective_block": [
                {
                    "name": "heads",
                    "uses_outputs": ["pz_01"],
                },
            ],
        },
        "bounds": {
            "K_alluvium": [1.0e-6, 1.0e-3],
            "K_basement": [0.1, 10.0],
        },
    }
    cfg = ModelCalibrationConfig.from_toml(raw_toml, base_dir=tmp_path)

    property_set = build_property_array_set(
        cfg=cfg,
        params={"K_alluvium": 3.0e-5, "K_basement": 2.0},
        base_property_arrays={"K": [1.0e-5, 2.0e-5, 4.0e-5]},
        lithology_labels=["alluvium", "basement", "basement"],
    )

    assert property_set.get("K").values.tolist() == pytest.approx(
        [3.0e-5, 4.0e-5, 8.0e-5]
    )
    assert property_set.get("K").labels == (
        "alluvium",
        "basement",
        "basement",
    )


def test_model_calibration_builds_weighted_zone_property_arrays(tmp_path: Path) -> None:
    raw_toml = {
        "model_calibration": {
            "simulation_config": "run_flow_reference.toml",
            "calibration_id": "calib_case_01",
            "parameter": [
                {
                    "name": "K_west",
                    "property": "K",
                    "target": "flow.param.K.values_by_key.west_zone",
                    "mode": "replace",
                    "parameterization": "lithology_value",
                },
            ],
            "output": [
                {
                    "name": "pz_01",
                    "variable": "watertable_elevation",
                    "support": "point",
                    "x": 1.0,
                    "y": 2.0,
                },
            ],
            "objective_block": [
                {
                    "name": "heads",
                    "uses_outputs": ["pz_01"],
                },
            ],
        },
        "bounds": {
            "K_west": [1.0e-6, 1.0e-3],
        },
    }
    cfg = ModelCalibrationConfig.from_toml(raw_toml, base_dir=tmp_path)

    property_set = build_property_array_set(
        cfg=cfg,
        params={"K_west": 4.0},
        base_property_arrays={"K": [1.75, 1.25, 1.0]},
        zone_fractions_by_key={
            "west_zone": [0.75, 0.25, 0.0],
            "east_zone": [0.25, 0.75, 1.0],
        },
        base_property_values_by_key={
            "K": {"west_zone": 2.0, "east_zone": 1.0},
        },
    )

    assert property_set.get("K").values.tolist() == pytest.approx(
        [3.25, 1.75, 1.0]
    )


def test_model_calibration_prepares_bundle_backed_property_support(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_calibration_bundle(tmp_path / "bundle")
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    simulation_path.write_text(
        simulation_path.read_text(encoding="utf-8")
        + "\n[mesh_input]\n"
        + f'bundle_dir = "{bundle_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    _write_minimal_model_calibration_config(config_path)

    launcher = ModelCalibrationLauncher(config_path)
    session = launcher.prepare()
    request = launcher.actualize_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
    )

    assert session.prepared_hydraulic_support is not None
    assert session.prepared_hydraulic_support.n_cells == 2
    assert session.prepared_hydraulic_support.lithology_labels == (
        "granite",
        "schist",
    )
    assert session.prepared_hydraulic_support.source == "mesh_input_bundle_dir_geology"
    assert session.prepared_hydraulic_support.mesh_bundle_dir == bundle_dir.resolve()
    assert session.prepared_hydraulic_support.mesh_path is None
    assert session.prepared_hydraulic_support.mesh_summary_path is None
    assert request.property_array_summary is not None
    assert request.property_array_summary["properties"]["K"]["stats"]["count"] == 2
    assert request.property_array_set is not None
    assert request.property_array_set.get("K").values.tolist() == pytest.approx(
        [2.0e-5, 4.0e-5]
    )


def test_model_calibration_prepares_bundle_support_from_mesh_input_mesh_path(
    tmp_path: Path,
) -> None:
    mesh_path = tmp_path / "mesh_catchment.msh"
    mesh_path.write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
    bundle_dir = _write_minimal_calibration_bundle(
        resolve_default_catchment_mesh_bundle_dir(mesh_path)
    )
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    simulation_path.write_text(
        simulation_path.read_text(encoding="utf-8")
        + "\n[mesh_input]\n"
        + f'mesh_path = "{mesh_path.as_posix()}"\n',
        encoding="utf-8",
    )
    _write_minimal_model_calibration_config(config_path)

    launcher = ModelCalibrationLauncher(config_path)
    session = launcher.prepare()
    request = launcher.actualize_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
    )

    assert session.prepared_hydraulic_support is not None
    assert (
        session.prepared_hydraulic_support.source
        == "mesh_input_mesh_path_default_bundle_geology"
    )
    assert session.prepared_hydraulic_support.mesh_bundle_dir == bundle_dir.resolve()
    assert session.prepared_hydraulic_support.mesh_path == mesh_path.resolve()
    assert request.property_array_set is not None
    assert request.property_array_set.get("K").values.tolist() == pytest.approx(
        [2.0e-5, 4.0e-5]
    )


def test_model_calibration_prepares_bundle_support_from_mesh_catchment_summary(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    simulation_path.write_text(
        simulation_path.read_text(encoding="utf-8")
        + "\n[mesh_catchment]\n"
        + 'constraints_mode = "rivers_only"\n',
        encoding="utf-8",
    )
    workspace_project_root = (tmp_path / "project" / "demo_case").resolve()
    mesh_dir = workspace_project_root / "results_stable" / "mesh"
    bundle_dir = _write_minimal_calibration_bundle(mesh_dir / "mesh_catchment_bundle")
    summary_path = _write_mesh_summary(
        mesh_dir / "mesh_catchment_summary.json",
        bundle_dir=bundle_dir,
        mesh_path=mesh_dir / "mesh_catchment.msh",
        relative_bundle_dir=True,
    )
    _write_minimal_model_calibration_config(config_path)

    launcher = ModelCalibrationLauncher(config_path)
    session = launcher.prepare()
    request = launcher.actualize_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
    )

    assert session.prepared_hydraulic_support is not None
    assert (
        session.prepared_hydraulic_support.source
        == "mesh_catchment_default_summary_bundle_geology"
    )
    assert session.prepared_hydraulic_support.mesh_bundle_dir == bundle_dir.resolve()
    assert (
        session.prepared_hydraulic_support.mesh_summary_path
        == summary_path.resolve()
    )
    assert (
        session.prepared_hydraulic_support.mesh_path
        == (mesh_dir / "mesh_catchment.msh").resolve()
    )
    assert request.property_array_set is not None
    assert request.property_array_set.get("K").values.tolist() == pytest.approx(
        [2.0e-5, 4.0e-5]
    )


def test_model_calibration_prepares_bundle_support_from_mesh_catchment_mesh_path(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    simulation_path.write_text(
        simulation_path.read_text(encoding="utf-8")
        + "\n[mesh_catchment]\n"
        + 'constraints_mode = "rivers_only"\n',
        encoding="utf-8",
    )
    workspace_project_root = (tmp_path / "project" / "demo_case").resolve()
    mesh_dir = workspace_project_root / "results_stable" / "mesh"
    mesh_path = mesh_dir / "mesh_catchment.msh"
    mesh_path.parent.mkdir(parents=True, exist_ok=True)
    mesh_path.write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
    bundle_dir = _write_minimal_calibration_bundle(
        resolve_default_catchment_mesh_bundle_dir(mesh_path)
    )
    _write_minimal_model_calibration_config(config_path)

    launcher = ModelCalibrationLauncher(config_path)
    session = launcher.prepare()
    request = launcher.actualize_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
    )

    assert session.prepared_hydraulic_support is not None
    assert (
        session.prepared_hydraulic_support.source
        == "mesh_catchment_default_mesh_default_bundle_geology"
    )
    assert session.prepared_hydraulic_support.mesh_bundle_dir == bundle_dir.resolve()
    assert session.prepared_hydraulic_support.mesh_path == mesh_path.resolve()
    assert session.prepared_hydraulic_support.mesh_summary_path is None
    assert request.property_array_set is not None
    assert request.property_array_set.get("K").values.tolist() == pytest.approx(
        [2.0e-5, 4.0e-5]
    )


def test_model_calibration_prefers_runtime_prepared_hydraulic_support(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_validation_dupuit_modflow6_simulation_config(
        simulation_path,
        project_root=tmp_path / "validation_project",
    )
    _write_dupuit_runtime_prepare_calibration_config(
        config_path,
        simulation_config_name=simulation_path.name,
    )

    launcher = ModelCalibrationLauncher(config_path)
    session = launcher.prepare()
    request = launcher.actualize_candidate(
        {"K_global_factor": 1.2},
        iteration_index=1,
    )

    assert session.prepared_hydraulic_support is not None
    assert session.prepared_hydraulic_support.source == "runtime_prepared_modflow6"
    assert session.prepared_hydraulic_support.n_cells == 200
    assert session.prepared_hydraulic_support.mesh_bundle_dir is None
    assert session.prepared_hydraulic_support.mesh_summary_path is None
    assert "K" in session.prepared_hydraulic_support.base_property_arrays
    assert request.property_array_set is not None
    assert request.property_array_set.get("K").values.size == 200
    assert request.property_array_set.get("K").values[0] == pytest.approx(1.2e-4)


def test_model_calibration_prepares_runtime_zone_supported_property_updates(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_runtime_zone_supported_simulation_config(simulation_path)
    _write_runtime_zone_calibration_config(
        config_path,
        simulation_config_name=simulation_path.name,
    )

    launcher = ModelCalibrationLauncher(config_path)
    session = launcher.prepare()
    request = launcher.actualize_candidate(
        {"K_west": 3.0e-4},
        iteration_index=1,
    )

    assert session.prepared_hydraulic_support is not None
    assert session.prepared_hydraulic_support.source == "runtime_prepared_modflow6_zones"
    assert session.prepared_hydraulic_support.n_cells == 200
    assert session.prepared_hydraulic_support.mesh_bundle_dir is None
    assert session.prepared_hydraulic_support.base_property_values_by_key["K"][
        "west_zone"
    ] == pytest.approx(2.0e-4)
    assert session.prepared_hydraulic_support.base_property_values_by_key["K"][
        "east_zone"
    ] == pytest.approx(5.0e-5)
    assert sorted(session.prepared_hydraulic_support.zone_fractions_by_key) == [
        "east_zone",
        "west_zone",
    ]
    assert request.override_payload["flow"]["param"]["K"]["field_heterogeneous"][
        "values"
    ]["west_zone"] == "0.0003 m/s"
    assert request.property_array_set is not None
    values_grid = request.property_array_set.get("K").values.reshape(5, 40)
    assert np.mean(values_grid[:, :20]) == pytest.approx(3.0e-4)
    assert np.mean(values_grid[:, 20:]) == pytest.approx(5.0e-5)


def test_model_calibration_bundle_change_updates_session_contract_signature(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_calibration_bundle(tmp_path / "bundle")
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    simulation_path.write_text(
        simulation_path.read_text(encoding="utf-8")
        + "\n[mesh_input]\n"
        + f'bundle_dir = "{bundle_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    _write_minimal_model_calibration_config(config_path)

    first_session = ModelCalibrationLauncher(config_path).prepare()
    first_signature = first_session.contract_signature
    first_support_signature = first_session.prepared_hydraulic_support.to_summary()[
        "base_property_details"
    ]["K"]["signature"]

    cells_path = bundle_dir / "cells.csv"
    cells_path.write_text(
        cells_path.read_text(encoding="utf-8")
        .replace("1.0e-5,0.10", "3.0e-5,0.10")
        .replace("2.0e-5,0.15", "4.0e-5,0.15"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="persisted session contract"):
        _ = ModelCalibrationLauncher(config_path).prepare()

    _write_minimal_model_calibration_config(
        config_path,
        resume_existing_session=False,
    )
    second_session = ModelCalibrationLauncher(config_path).prepare()
    second_signature = second_session.contract_signature
    second_support_signature = second_session.prepared_hydraulic_support.to_summary()[
        "base_property_details"
    ]["K"]["signature"]

    assert second_support_signature != first_support_signature
    assert second_signature != first_signature


def test_model_calibration_run_candidate_injects_flow_runtime_overrides(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(config_path)
    launcher = ModelCalibrationLauncher(config_path)

    captured: dict[str, object] = {}

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)
            self.run_state = SimpleNamespace(setup=SimpleNamespace())

        def run(self):
            captured["flow_runtime_overrides"] = (
                self.run_state.setup.flow_runtime_overrides
            )
            return {"mode": "simulation", "config": str(self.candidate_config_path)}

    outcome = launcher.run_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
        launcher_factory=_FakeSimulationLauncher,
    )

    assert outcome.status == "solver_run_succeeded"
    overrides = captured["flow_runtime_overrides"]
    assert isinstance(overrides, dict)
    assert overrides["source"] == "model_calibration"
    assert overrides["candidate_run_id"] == "calib_case_01__iter_0001"
    assert overrides["properties"]["K"].tolist() == pytest.approx([1.0e-4])
    assert overrides["properties"]["Sy"].tolist() == pytest.approx([0.15])


def test_model_calibration_run_candidate_persists_iteration_history(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(config_path)
    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            return {"mode": "simulation", "config": str(self.candidate_config_path)}

    outcome = launcher.run_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
        launcher_factory=_FakeSimulationLauncher,
    )

    assert outcome.status == "solver_run_succeeded"
    assert outcome.run_state["mode"] == "simulation"

    summary = launcher.run()
    assert summary["iteration_count"] == 1
    assert summary["last_iteration_id"] == "iter_0001"
    assert summary["last_iteration_status"] == "solver_run_succeeded"

    history_lines = Path(summary["iteration_history_path"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(history_lines) == 1
    payload = json.loads(history_lines[0])
    assert payload["iteration_id"] == "iter_0001"
    assert payload["objective_total"] is None
    assert payload["status"] == "solver_run_succeeded"
    assert payload["failure_reason"] is None


def test_model_calibration_can_disable_iteration_history_file(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        persist_iteration_history=False,
    )
    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            return {"mode": "simulation", "config": str(self.candidate_config_path)}

    outcome = launcher.run_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
        launcher_factory=_FakeSimulationLauncher,
    )

    assert outcome.status == "solver_run_succeeded"
    summary = launcher.run()
    assert summary["iteration_count"] == 1
    assert summary["last_iteration_id"] == "iter_0001"
    assert summary["persist_iteration_history"] is False
    assert not Path(summary["iteration_history_path"]).exists()


def test_model_calibration_prepare_can_resume_existing_session(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
    )

    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            return {
                "calibration_outputs": {
                    "pz_01": [11.0, 13.0],
                    "q_outlet_lowflow_mean": [5.0, 7.0],
                },
            }

    _ = launcher.run_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
        launcher_factory=_FakeSimulationLauncher,
    )

    resumed_launcher = ModelCalibrationLauncher(config_path)
    summary = resumed_launcher.run()

    assert summary["status"] == "resumed_prepared"
    assert summary["iteration_count"] == 1
    assert summary["resumed_iteration_count"] == 1
    history_lines = Path(summary["iteration_history_path"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(history_lines) == 1


def test_model_calibration_prepare_rejects_resume_when_contract_changed(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(config_path)

    _ = ModelCalibrationLauncher(config_path).run()
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("x = 1.0", "x = 1.5", 1),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Cannot resume calibration session",
    ):
        ModelCalibrationLauncher(config_path).run()


def test_model_calibration_prepare_marks_legacy_manifest_as_not_reusable(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
    )

    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            return {
                "calibration_outputs": {
                    "pz_01": [11.0, 13.0],
                    "q_outlet_lowflow_mean": [5.0, 7.0],
                },
            }

    _ = launcher.run_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
        launcher_factory=_FakeSimulationLauncher,
    )

    manifest_path = Path(launcher.run()["session_manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("session_contract_signature", None)
    manifest.pop("persisted_iteration_reuse_allowed", None)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    resumed_summary = ModelCalibrationLauncher(config_path).run()

    assert resumed_summary["status"] == "resumed_prepared"
    assert resumed_summary["persisted_iteration_reuse_allowed"] is False


def test_model_calibration_evaluator_reuses_persisted_iterations(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
    )

    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            return {
                "calibration_outputs": {
                    "pz_01": [11.0, 13.0],
                    "q_outlet_lowflow_mean": [5.0, 7.0],
                },
            }

    first_outcome = launcher.run_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
        launcher_factory=_FakeSimulationLauncher,
    )
    assert first_outcome.objective_evaluation is not None

    resumed_launcher = ModelCalibrationLauncher(config_path)
    session = resumed_launcher.prepare()

    class _UnexpectedSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            raise AssertionError("persisted iteration should avoid solver rerun")

    evaluator = ModelCalibrationObjectiveEvaluator(
        session=session,
        cfg=resumed_launcher.cfg,
        launcher_factory=_UnexpectedSimulationLauncher,
    )

    evaluation = evaluator.evaluate(
        {"K_global_factor": 2.0, "Sy_global": 0.15}
    )

    assert evaluation.total_cost == pytest.approx(0.5)
    assert evaluator.restored_evaluation_count == 1
    assert evaluator.cache_hit_count == 1
    assert evaluator.candidate_run_count == 0
    assert len(evaluator.empirical_iteration_records) == 1


def test_model_calibration_run_candidate_evaluates_composite_objective(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
    )
    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            return {
                "mode": "simulation",
                "config": str(self.candidate_config_path),
                "calibration_outputs": {
                    "pz_01": [11.0, 13.0],
                    "q_outlet_lowflow_mean": [5.0, 7.0],
                },
            }

    outcome = launcher.run_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
        launcher_factory=_FakeSimulationLauncher,
    )

    assert outcome.status == "objective_evaluated"
    assert outcome.objective_evaluation is not None
    assert outcome.objective_evaluation.total_cost == pytest.approx(0.5)
    assert {
        block.name: block.normalized_cost for block in outcome.objective_evaluation.blocks
    } == {
        "heads": pytest.approx(0.5),
        "flux": pytest.approx(0.5),
    }

    summary = launcher.run()
    assert summary["iteration_count"] == 1
    assert summary["last_iteration_status"] == "objective_evaluated"

    history_lines = Path(summary["iteration_history_path"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(history_lines) == 1
    payload = json.loads(history_lines[0])
    assert payload["objective_total"] == pytest.approx(0.5)
    assert payload["block_costs"] == {
        "heads": pytest.approx(0.5),
        "flux": pytest.approx(0.5),
    }
    assert payload["status"] == "objective_evaluated"
    assert payload["failure_reason"] is None


def test_model_calibration_run_candidate_can_persist_diagnostic_iteration(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
        persist_iteration_detail_level="diagnostic",
    )
    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            return {
                "calibration_outputs": {
                    "pz_01": [11.0, 13.0],
                    "q_outlet_lowflow_mean": [5.0, 7.0],
                },
            }

    _ = launcher.run_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
        launcher_factory=_FakeSimulationLauncher,
    )
    summary = launcher.run()

    payload = json.loads(
        Path(summary["iteration_history_path"]).read_text(encoding="utf-8")
    )
    assert payload["objective_score"] == pytest.approx(-0.5)
    assert payload["candidate_run_id"] == "calib_case_01__iter_0001"
    assert payload["candidate_config_path"].endswith("candidate_override.toml")
    assert [block["name"] for block in payload["block_details"]] == [
        "heads",
        "flux",
    ]
    assert payload["block_details"][0]["raw_cost"] == pytest.approx(1.0)


def test_model_calibration_run_candidate_records_objective_failure(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
    )
    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            return {
                "mode": "simulation",
                "config": str(self.candidate_config_path),
                "calibration_outputs": {
                    "pz_01": [11.0, 13.0],
                },
            }

    outcome = launcher.run_candidate(
        {"K_global_factor": 2.0, "Sy_global": 0.15},
        iteration_index=1,
        launcher_factory=_FakeSimulationLauncher,
    )

    assert outcome.status == "objective_evaluation_failed"
    assert outcome.error_type == "KeyError"
    assert outcome.error_message is not None
    assert "q_outlet_lowflow_mean" in outcome.error_message

    summary = launcher.run()
    assert summary["iteration_count"] == 1
    assert summary["last_iteration_status"] == "objective_evaluation_failed"

    history_lines = Path(summary["iteration_history_path"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(history_lines) == 1
    payload = json.loads(history_lines[0])
    assert math.isinf(payload["objective_total"])
    assert payload["block_costs"] == {}
    assert payload["status"] == "objective_evaluation_failed"
    assert payload["failure_reason"] == outcome.error_message


def test_model_calibration_objective_records_parameter_injection_failure(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
    )
    config_text = config_path.read_text(encoding="utf-8").replace(
        'target = "flow.param.K.field_homogeneous.value"',
        'target = "flow.param.K.missing.value"',
        1,
    )
    config_path.write_text(config_text, encoding="utf-8")
    launcher = ModelCalibrationLauncher(config_path)
    session = launcher.prepare()
    records: list[IterationRecord] = []

    class _UnexpectedSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = candidate_config_path

        def run(self):
            raise AssertionError("parameter injection failure should skip solver run")

    evaluator = ModelCalibrationObjectiveEvaluator(
        session=session,
        cfg=launcher.cfg,
        launcher_factory=_UnexpectedSimulationLauncher,
        record_callback=records.append,
    )

    evaluation = evaluator.evaluate(
        {"K_global_factor": 2.0, "Sy_global": 0.15}
    )

    assert math.isinf(evaluation.total_cost)
    assert evaluation.metadata["status"] == "parameter_injection_failed"
    assert len(records) == 1
    assert records[0].status == "parameter_injection_failed"
    assert math.isinf(records[0].objective_total)
    assert "flow.param.K.missing" in str(records[0].failure_reason)


def test_model_calibration_calibrate_runs_engine_loop_and_persists_result(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
    )
    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            merged = load_toml_with_base_config(self.candidate_config_path)
            k_value = float(
                str(
                    merged["flow"]["param"]["K"]["field_homogeneous"]["value"]
                ).split()[0]
            )
            sy_value = float(
                str(
                    merged["flow"]["param"]["Sy"]["field_homogeneous"]["value"]
                ).split()[0]
            )
            if k_value == pytest.approx(1.0e-4) and sy_value == pytest.approx(0.15):
                heads = [10.0, 14.0]
                flux = [4.0, 8.0]
            else:
                heads = [11.0, 13.0]
                flux = [5.0, 7.0]
            return {
                "calibration_outputs": {
                    "pz_01": heads,
                    "q_outlet_lowflow_mean": flux,
                },
            }

    class _FakeCalibrationMethod:
        def calibrate(self, objective_cost, bounds, method="simplex", **kwargs):
            _ = bounds, kwargs
            first = [1.0, 0.10]
            second = [2.0, 0.15]
            first_cost = float(objective_cost(first))
            second_cost = float(objective_cost(second))
            if second_cost <= first_cost:
                return {
                    "method": method,
                    "x_best": second,
                    "cost_best": second_cost,
                    "n_evaluations": 2,
                }
            return {
                "method": method,
                "x_best": first,
                "cost_best": first_cost,
                "n_evaluations": 2,
            }

    summary = launcher.calibrate(
        launcher_factory=_FakeSimulationLauncher,
        calibration_method=_FakeCalibrationMethod(),
    )

    assert summary["status"] == "calibrated"
    assert summary["iteration_count"] == 2
    assert summary["candidate_run_count"] == 2
    assert summary["objective_cache_hit_count"] == 1
    assert summary["cost_best"] == pytest.approx(0.0)
    assert summary["best_rerun"]["status"] == "solver_run_succeeded"
    assert summary["calibration_report"]["iteration_count"] == 2
    assert summary["calibration_report"]["failed_count"] == 0
    assert summary["params_best"] == {
        "K_global_factor": pytest.approx(2.0),
        "Sy_global": pytest.approx(0.15),
    }

    best_rerun_config = load_toml_with_base_config(
        Path(summary["best_rerun"]["candidate_config_path"])
    )
    assert best_rerun_config["simulation"]["run_id"] == "calib_case_01__best"
    assert best_rerun_config["display"]["enabled"] is True
    assert best_rerun_config["postprocess"]["enabled"] is True

    result_path = Path(summary["result_path"])
    assert result_path.is_file()
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_payload["method"] == "simplex"
    assert result_payload["cost_best"] == pytest.approx(0.0)
    assert result_payload["params_best"] == {
        "K_global_factor": pytest.approx(2.0),
        "Sy_global": pytest.approx(0.15),
    }
    assert result_payload["metadata"]["objective_evaluation"]["total_cost"] == (
        pytest.approx(0.0)
    )

    report_path = Path(summary["calibration_report"]["path"])
    assert report_path.is_file()
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["role"] == "model_calibration_report"
    assert report_payload["best_model"]["cost_best"] == pytest.approx(0.0)
    assert report_payload["iterations"]["count"] == 2
    assert report_payload["iterations"]["status_counts"] == {
        "objective_evaluated": 2
    }
    assert report_payload["blocks"]["heads"]["best_value"] == pytest.approx(0.0)
    assert report_payload["parameters"]["K_global_factor"]["best_value"] == (
        pytest.approx(2.0)
    )
    assert sorted(report_payload["hydraulic_parameterization"].keys()) == ["K", "Sy"]

    history_lines = Path(summary["iteration_history_path"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(history_lines) == 2
    history_payloads = [json.loads(line) for line in history_lines]
    assert [item["status"] for item in history_payloads] == [
        "objective_evaluated",
        "objective_evaluated",
    ]
    assert history_payloads[-1]["objective_total"] == pytest.approx(0.0)


def test_model_calibration_calibrate_writes_objective_mapping_artifacts(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
        objective_mapping_enabled=True,
        objective_mapping_additional_runs=2,
        objective_mapping_interpolation="linear",
    )
    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            merged = load_toml_with_base_config(self.candidate_config_path)
            k_value = float(
                str(
                    merged["flow"]["param"]["K"]["field_homogeneous"]["value"]
                ).split()[0]
            )
            sy_value = float(
                str(
                    merged["flow"]["param"]["Sy"]["field_homogeneous"]["value"]
                ).split()[0]
            )
            k_factor = k_value / 5.0e-5
            misfit = abs(k_factor - 2.0) + abs(sy_value - 0.15)
            return {
                "calibration_outputs": {
                    "pz_01": [10.0 + misfit, 14.0 + misfit],
                    "q_outlet_lowflow_mean": [4.0 + misfit, 8.0 + misfit],
                },
            }

    class _FakeCalibrationMethod:
        def calibrate(self, objective_cost, bounds, method="simplex", **kwargs):
            _ = bounds, kwargs
            first = [1.0, 0.10]
            second = [2.0, 0.15]
            _ = float(objective_cost(first))
            best_cost = float(objective_cost(second))
            return {
                "method": method,
                "x_best": second,
                "cost_best": best_cost,
                "n_evaluations": 2,
            }

    summary = launcher.calibrate(
        launcher_factory=_FakeSimulationLauncher,
        calibration_method=_FakeCalibrationMethod(),
    )

    mapping = summary["objective_mapping"]
    assert mapping["status"] == "completed"
    assert mapping["axes"] == ["K_global_factor", "Sy_global"]
    assert mapping["additional_runs_executed"] == 2
    assert mapping["point_count"] == 4
    assert mapping["finite_point_count"] == 4
    assert mapping["interpolation_requested"] == "linear"
    assert mapping["interpolation_used"] in {"linear", "idw_fallback"}

    points_path = Path(mapping["points_csv"])
    grid_path = Path(mapping["grid_json"])
    assert points_path.is_file()
    assert grid_path.is_file()
    if mapping["figure_written"]:
        assert Path(mapping["figure"]).is_file()

    csv_lines = points_path.read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 5
    assert "block_heads" in csv_lines[0]
    grid_payload = json.loads(grid_path.read_text(encoding="utf-8"))
    assert grid_payload["role"] == "objective_function_mapping"
    assert grid_payload["additional_runs_executed"] == 2
    assert grid_payload["grid"]["axes"] == ["K_global_factor", "Sy_global"]
    assert "heads" in grid_payload["grid"]["block_costs"]

    history_lines = Path(summary["iteration_history_path"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(history_lines) == 4
    assert summary["candidate_run_count"] == 4


def test_model_calibration_calibrate_persists_posterior_model_distribution(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
        global_method="da_mh_gp",
    )
    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            merged = load_toml_with_base_config(self.candidate_config_path)
            sy_value = float(
                str(
                    merged["flow"]["param"]["Sy"]["field_homogeneous"]["value"]
                ).split()[0]
            )
            if sy_value == pytest.approx(0.15):
                heads = [10.0, 14.0]
                flux = [4.0, 8.0]
            else:
                heads = [11.0, 13.0]
                flux = [5.0, 7.0]
            return {
                "calibration_outputs": {
                    "pz_01": heads,
                    "q_outlet_lowflow_mean": flux,
                },
            }

    class _FakePosteriorCalibrationMethod:
        def calibrate(self, objective_cost, bounds, method="da_mh_gp", **kwargs):
            _ = bounds, kwargs
            first = [1.0, 0.10]
            second = [2.0, 0.15]
            _ = float(objective_cost(first))
            best_cost = float(objective_cost(second))
            return {
                "method": method,
                "x_best": second,
                "cost_best": best_cost,
                "n_evaluations": 2,
                "posterior_samples": [
                    [1.0, 0.10],
                    [2.0, 0.15],
                    [3.0, 0.20],
                ],
            }

    summary = launcher.calibrate(
        launcher_factory=_FakeSimulationLauncher,
        calibration_method=_FakePosteriorCalibrationMethod(),
    )

    distribution = summary["model_distribution"]
    assert distribution["role"] == "posterior_parameter_distribution"
    assert distribution["method"] == "da_mh_gp"
    assert distribution["sample_count"] == 3

    payload = json.loads(Path(distribution["path"]).read_text(encoding="utf-8"))
    assert payload["role"] == "posterior_parameter_distribution"
    assert payload["source"] == "CalibrationResults.samples"
    assert payload["parameter_names"] == ["K_global_factor", "Sy_global"]
    assert payload["statistics"]["K_global_factor"]["q50"] == pytest.approx(2.0)
    assert payload["samples"][1]["params_named"] == {
        "K_global_factor": pytest.approx(2.0),
        "Sy_global": pytest.approx(0.15),
    }


def test_model_calibration_can_rerun_posterior_model_distribution_subset(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
        global_method="da_mh_gp",
        rerun_model_distribution_with_outputs=True,
        model_distribution_max_reruns=2,
        model_distribution_rerun_selection="representative",
    )
    launcher = ModelCalibrationLauncher(config_path)
    run_ids: list[str] = []

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            merged = load_toml_with_base_config(self.candidate_config_path)
            run_ids.append(merged["simulation"]["run_id"])
            return {
                "calibration_outputs": {
                    "pz_01": [10.0, 14.0],
                    "q_outlet_lowflow_mean": [4.0, 8.0],
                },
            }

    class _FakePosteriorCalibrationMethod:
        def calibrate(self, objective_cost, bounds, method="da_mh_gp", **kwargs):
            _ = bounds, kwargs
            _ = float(objective_cost([1.0, 0.10]))
            best_cost = float(objective_cost([2.0, 0.15]))
            return {
                "method": method,
                "x_best": [2.0, 0.15],
                "cost_best": best_cost,
                "n_evaluations": 2,
                "posterior_samples": [
                    [1.0, 0.10],
                    [1.5, 0.12],
                    [2.0, 0.15],
                    [2.5, 0.18],
                    [3.0, 0.20],
                ],
            }

    summary = launcher.calibrate(
        launcher_factory=_FakeSimulationLauncher,
        calibration_method=_FakePosteriorCalibrationMethod(),
    )

    rerun_summary = summary["model_distribution_rerun"]
    assert rerun_summary["status"] == "completed"
    assert rerun_summary["selection"] == "representative"
    assert rerun_summary["selected_count"] == 2

    rerun_payload = json.loads(
        Path(rerun_summary["path"]).read_text(encoding="utf-8")
    )
    assert rerun_payload["role"] == "model_distribution_output_reruns"
    assert rerun_payload["source_model_distribution_role"] == (
        "posterior_parameter_distribution"
    )
    assert len(rerun_payload["reruns"]) == 2
    assert all(
        row["status"] == "solver_run_succeeded"
        for row in rerun_payload["reruns"]
    )
    assert all(
        row["candidate_run_id"].startswith("calib_case_01__ensemble_")
        for row in rerun_payload["reruns"]
    )

    for row in rerun_payload["reruns"]:
        merged = load_toml_with_base_config(Path(row["candidate_config_path"]))
        assert merged["display"]["enabled"] is True
        assert merged["postprocess"]["enabled"] is True

    history_lines = Path(summary["iteration_history_path"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(history_lines) == 2
    assert "calib_case_01__best" in run_ids
    assert (
        sum(run_id.startswith("calib_case_01__ensemble_") for run_id in run_ids)
        == 2
    )


def test_model_calibration_calibrate_persists_random_search_empirical_ensemble(
    tmp_path: Path,
) -> None:
    simulation_path = tmp_path / "run_flow_reference.toml"
    config_path = tmp_path / "config_model_calibration.toml"
    _write_minimal_simulation_config(simulation_path)
    _write_minimal_model_calibration_config(
        config_path,
        include_observed_values=True,
        global_method="random_search",
    )
    launcher = ModelCalibrationLauncher(config_path)

    class _FakeSimulationLauncher:
        def __init__(self, candidate_config_path: Path) -> None:
            self.candidate_config_path = Path(candidate_config_path)

        def run(self):
            merged = load_toml_with_base_config(self.candidate_config_path)
            sy_value = float(
                str(
                    merged["flow"]["param"]["Sy"]["field_homogeneous"]["value"]
                ).split()[0]
            )
            if sy_value == pytest.approx(0.15):
                heads = [10.0, 14.0]
                flux = [4.0, 8.0]
            else:
                heads = [11.0, 13.0]
                flux = [5.0, 7.0]
            return {
                "calibration_outputs": {
                    "pz_01": heads,
                    "q_outlet_lowflow_mean": flux,
                },
            }

    class _FakeRandomSearchMethod:
        def calibrate(self, objective_cost, bounds, method="random_search", **kwargs):
            _ = bounds, kwargs
            first = [1.0, 0.10]
            second = [2.0, 0.15]
            first_cost = float(objective_cost(first))
            second_cost = float(objective_cost(second))
            return {
                "method": method,
                "x_best": second,
                "cost_best": min(first_cost, second_cost),
                "n_evaluations": 2,
            }

    summary = launcher.calibrate(
        launcher_factory=_FakeSimulationLauncher,
        calibration_method=_FakeRandomSearchMethod(),
    )

    distribution = summary["model_distribution"]
    assert distribution["role"] == "empirical_evaluated_model_ensemble"
    assert distribution["method"] == "random_search"
    assert distribution["sample_count"] == 2

    payload = json.loads(Path(distribution["path"]).read_text(encoding="utf-8"))
    assert payload["source"] == "evaluated_candidates"
    assert payload["statistics"]["Sy_global"]["max"] == pytest.approx(0.15)
    assert [sample["status"] for sample in payload["samples"]] == [
        "objective_evaluated",
        "objective_evaluated",
    ]
    assert payload["samples"][1]["objective_total"] == pytest.approx(0.0)


def test_launchers_cli_model_calibration_run_dispatches_to_launcher(
    monkeypatch,
) -> None:
    module = _load_launchers_main_module()
    captured: dict[str, Path] = {}

    config_path = Path("sample_model_calibration.toml")

    def _fake_runner(path: Path) -> None:
        captured["config"] = path

    monkeypatch.setattr(module, "_run_model_calibration_launcher", _fake_runner)

    code = module.main(["model-calibration", "run", str(config_path)])

    assert code == 0
    assert captured["config"] == config_path.resolve()


def test_launchers_cli_model_calibration_template_prints_template(capsys) -> None:
    module = _load_launchers_main_module()

    code = module.main(["model-calibration", "template"])
    captured = capsys.readouterr()

    assert code == 0
    assert "[model_calibration]" in captured.out
    assert "[[model_calibration.parameter]]" in captured.out
    assert "weighted_interpolation" in captured.out
