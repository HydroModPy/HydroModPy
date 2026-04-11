from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from launchers.model_calibration.config import ModelCalibrationConfig
from launchers.model_calibration.launcher import ModelCalibrationLauncher
from launchers.model_calibration.runtime import (
    IterationRecord,
    ModelCalibrationObjectiveEvaluator,
    append_iteration_record,
    select_candidate_outputs,
)
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
    global_method: str = "simplex",
    rerun_model_distribution_with_outputs: bool = False,
    model_distribution_max_reruns: int = 10,
    model_distribution_rerun_selection: str = "representative",
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
                "persist_iteration_history = true",
                'persist_iteration_detail_level = "minimal"',
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
