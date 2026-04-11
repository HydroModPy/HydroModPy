from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from launchers.model_calibration.config import ModelCalibrationConfig
from launchers.model_calibration.launcher import ModelCalibrationLauncher
from launchers.model_calibration.runtime import IterationRecord, append_iteration_record
from launchers.model_calibration.templates import render_model_calibration_template


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


def _write_minimal_model_calibration_config(
    path: Path,
    *,
    include_observed_values: bool = False,
) -> None:
    head_observations = (
        ['observed_values = [10.0, 14.0]'] if include_observed_values else []
    )
    flux_observations = (
        ['observed_values = [4.0, 8.0]'] if include_observed_values else []
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
                "persist_iteration_history = true",
                'persist_iteration_detail_level = "minimal"',
                "",
                "[calibration]",
                'objective_metric = "rmse"',
                'global_method = "simplex"',
                "",
                "[objective]",
                'transform = "identity"',
                "",
                "[calibration_method.simplex]",
                "max_iter = 50",
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
    assert manifest["primary_solver"] == "modflow6"


def test_model_calibration_template_contains_expected_sections() -> None:
    content = render_model_calibration_template()

    assert "[model_calibration]" in content
    assert "[[model_calibration.parameter]]" in content
    assert "[[model_calibration.output]]" in content
    assert "[[model_calibration.objective_block]]" in content
    assert 'reducer = "weighted_interpolation"' in content


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

    merged = load_toml_with_base_config(request.candidate_config_path)
    assert merged["simulation"]["run_id"] == "calib_case_01__iter_0001"
    assert merged["flow"]["param"]["K"]["field_homogeneous"]["value"] == "0.0001 m/s"
    assert merged["flow"]["param"]["Sy"]["field_homogeneous"]["value"] == "0.15 -"
    assert merged["display"]["enabled"] is False
    assert merged["display"]["show"] is False
    assert merged["postprocess"]["enabled"] is False


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
