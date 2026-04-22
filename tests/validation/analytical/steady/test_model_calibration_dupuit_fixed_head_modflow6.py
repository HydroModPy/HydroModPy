"""End-to-end calibration check for the steady Dupuit fixed-head MODFLOW 6 case."""

from __future__ import annotations

import pytest

pytest.skip(
    "legacy ModelCalibrationLauncher superseded by P09 hydromodpy/calibration",
    allow_module_level=True,
)

import math  # noqa: E402
from pathlib import Path  # noqa: E402

from hydromodpy.analysis.calibration.engine.launcher import ModelCalibrationLauncher  # noqa: E402
from hydromodpy.analysis.calibration.engine.session import (  # noqa: E402
    actualize_candidate,
    select_candidate_outputs,
)
from hydromodpy.project import Project
from tests.regression.golden_utils import assert_required_executables
from validation_cases.shared.runtime import (
    _dump_toml,
    _merge_toml_payloads,
    _read_toml,
)

CASE_DIR = (
    Path(__file__).resolve().parents[4]
    / "validation_cases"
    / "analytical"
    / "steady"
    / "dupuit_fixed_head_1d"
)
TRANSIENT_CASE_DIR = (
    Path(__file__).resolve().parents[4]
    / "validation_cases"
    / "analytical"
    / "transient"
    / "linearized_unconfined_recharge_step_1d"
)


def _write_validation_dupuit_modflow6_simulation_config(path: Path, *, project_root: Path) -> None:
    payload = _merge_toml_payloads(
        _read_toml(CASE_DIR / "config_common.toml"),
        _read_toml(CASE_DIR / "config_modflow6.toml"),
    )
    payload.setdefault("workspace", {})["project_root"] = str(project_root)
    payload.setdefault("simulation", {})["run_id"] = "dcal"
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def _write_calibration_config(
    path: Path,
    *,
    simulation_config_name: str,
    calibration_id: str,
    observed_flux: float,
    bound_min: float = 0.999,
    bound_max: float = 1.001,
) -> None:
    path.write_text(
        "\n".join(
            [
                "[model_calibration]",
                f'simulation_config = "{simulation_config_name}"',
                f'calibration_id = "{calibration_id}"',
                "disable_display = true",
                "disable_postprocess = true",
                "rerun_best_with_outputs = false",
                "persist_model_distribution = false",
                "persist_iteration_history = true",
                'persist_iteration_detail_level = "minimal"',
                "persist_calibration_report = true",
                "resume_existing_session = false",
                "reuse_persisted_iterations = false",
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
                f"observed_values = [{observed_flux:.12g}]",
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
                f"K_global_factor = [{bound_min:.12g}, {bound_max:.12g}]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _format_float_list(values: list[float] | tuple[float, ...]) -> str:
    """Format one numeric sequence as an inline TOML float list."""
    return "[" + ", ".join(f"{float(value):.12g}" for value in values) + "]"


def _write_validation_transient_modflow6_simulation_config(
    path: Path,
    *,
    project_root: Path,
) -> None:
    payload = _merge_toml_payloads(
        _read_toml(TRANSIENT_CASE_DIR / "config_modflownwt.toml"),
        _read_toml(TRANSIENT_CASE_DIR / "config_modflow6.toml"),
    )
    payload.setdefault("workspace", {})["project_root"] = str(project_root)
    payload.setdefault("simulation", {})["run_id"] = "lcal_transient"
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def _write_transient_calibration_config(
    path: Path,
    *,
    simulation_config_name: str,
    calibration_id: str,
    observed_heads: tuple[float, ...],
    observed_flux: tuple[float, ...],
) -> None:
    path.write_text(
        "\n".join(
            [
                "[model_calibration]",
                f'simulation_config = "{simulation_config_name}"',
                f'calibration_id = "{calibration_id}"',
                "disable_display = true",
                "disable_postprocess = true",
                "rerun_best_with_outputs = false",
                "persist_model_distribution = false",
                "persist_iteration_history = true",
                'persist_iteration_detail_level = "minimal"',
                "persist_calibration_report = true",
                "resume_existing_session = false",
                "reuse_persisted_iterations = false",
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
                'name = "head_mid"',
                'variable = "watertable_elevation"',
                'source = "runtime"',
                'support = "point"',
                "x = 50.0",
                "y = 5.0",
                'time = "all"',
                f"observed_values = {_format_float_list(observed_heads)}",
                "",
                "[[model_calibration.output]]",
                'name = "q_east"',
                'variable = "outlet_discharge"',
                'source = "runtime"',
                'support = "boundary"',
                'boundary_id = "east_side"',
                'time = "all"',
                f"observed_values = {_format_float_list(observed_flux)}",
                "",
                "[[model_calibration.objective_block]]",
                'name = "heads"',
                'metric = "rmse"',
                "weight = 1.0",
                'uses_outputs = ["head_mid"]',
                "normalize_cost = true",
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
                'global_method = "simplex"',
                "",
                "[objective]",
                'transform = "identity"',
                "",
                "[calibration_method.simplex]",
                "max_iter = 5",
                "",
                "[bounds]",
                "K_global_factor = [0.95, 1.05]",
                "Sy_global = [0.05, 0.20]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _extract_reference_flux(
    *,
    simulation_path: Path,
    calibration_path: Path,
) -> float:
    _write_calibration_config(
        calibration_path,
        simulation_config_name=simulation_path.name,
        calibration_id="dref",
        observed_flux=0.0,
    )
    launcher = ModelCalibrationLauncher(calibration_path)
    request = actualize_candidate(
        session=launcher.prepare(),
        cfg=launcher.cfg,
        params={"K_global_factor": 1.0},
        candidate_label="r",
        disable_postprocess=False,
    )
    project = Project(request.candidate_config_path, headless=True)
    project.run()
    selected = select_candidate_outputs(
        cfg=launcher.cfg,
        run_state=project._ctx,
        session=request.session,
    )
    project.close()
    return float(selected["q_east"][0])


def _extract_reference_transient_outputs(
    *,
    simulation_path: Path,
    calibration_path: Path,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    _write_transient_calibration_config(
        calibration_path,
        simulation_config_name=simulation_path.name,
        calibration_id="lref",
        observed_heads=(0.0,),
        observed_flux=(0.0,),
    )
    launcher = ModelCalibrationLauncher(calibration_path)
    request = actualize_candidate(
        session=launcher.prepare(),
        cfg=launcher.cfg,
        params={"K_global_factor": 1.0, "Sy_global": 0.10},
        candidate_label="r",
        disable_postprocess=False,
    )
    project = Project(request.candidate_config_path, headless=True)
    project.run()
    selected = select_candidate_outputs(
        cfg=launcher.cfg,
        run_state=project._ctx,
        session=request.session,
    )
    project.close()
    return tuple(selected["head_mid"]), tuple(selected["q_east"])


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
def test_model_calibration_dupuit_fixed_head_modflow6_runs_end_to_end(
    tmp_path: Path,
) -> None:
    """Run one real MODFLOW 6 calibration using runtime-prepared hydraulic support."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    simulation_path = tmp_path / "r.toml"
    calibration_path = tmp_path / "c.toml"
    _write_validation_dupuit_modflow6_simulation_config(
        simulation_path,
        project_root=tmp_path / "p",
    )
    observed_flux = _extract_reference_flux(
        simulation_path=simulation_path,
        calibration_path=tmp_path / "cr.toml",
    )
    _write_calibration_config(
        calibration_path,
        simulation_config_name=simulation_path.name,
        calibration_id="dcal",
        observed_flux=observed_flux,
    )

    summary = ModelCalibrationLauncher(calibration_path).calibrate()

    assert summary["status"] == "calibrated"
    assert summary["primary_solver"] == "modflow6"
    assert summary["iteration_count"] >= 1
    assert math.isfinite(float(summary["cost_best"]))
    assert 0.999 <= float(summary["params_best"]["K_global_factor"]) <= 1.001
    assert summary["prepared_hydraulic_support"]["source"] == "runtime_prepared_modflow6"
    assert summary["prepared_hydraulic_support"]["n_cells"] == 200
    assert Path(summary["session_manifest_path"]).is_file()
    assert Path(summary["calibration_root"]).joinpath("calibration_report.json").is_file()


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
def test_model_calibration_linearized_recharge_step_modflow6_runs_multiobservable_ksy(
    tmp_path: Path,
) -> None:
    """Run one real transient MODFLOW 6 calibration with K+Sy and two observable blocks."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    simulation_path = tmp_path / "rt.toml"
    calibration_path = tmp_path / "ct.toml"
    _write_validation_transient_modflow6_simulation_config(
        simulation_path,
        project_root=tmp_path / "pt",
    )
    observed_heads, observed_flux = _extract_reference_transient_outputs(
        simulation_path=simulation_path,
        calibration_path=tmp_path / "crt.toml",
    )
    _write_transient_calibration_config(
        calibration_path,
        simulation_config_name=simulation_path.name,
        calibration_id="lcal",
        observed_heads=observed_heads,
        observed_flux=observed_flux,
    )

    class _ExactVectorMethod:
        def calibrate(self, objective_cost, bounds, method="simplex", **kwargs):
            _ = bounds, kwargs
            best = [1.0, 0.10]
            best_cost = float(objective_cost(best))
            return {
                "method": method,
                "x_best": best,
                "cost_best": best_cost,
                "n_evaluations": 1,
            }

    summary = ModelCalibrationLauncher(calibration_path).calibrate(
        calibration_method=_ExactVectorMethod(),
    )

    assert summary["status"] == "calibrated"
    assert summary["primary_solver"] == "modflow6"
    assert summary["iteration_count"] >= 1
    assert math.isfinite(float(summary["cost_best"]))
    assert float(summary["cost_best"]) == pytest.approx(0.0, abs=1.0e-6)
    assert summary["params_best"]["K_global_factor"] == pytest.approx(1.0)
    assert summary["params_best"]["Sy_global"] == pytest.approx(0.10)
    assert summary["prepared_hydraulic_support"]["source"] == "runtime_prepared_modflow6"
    assert summary["prepared_hydraulic_support"]["base_properties"] == ["K", "Sy"]
    assert Path(summary["session_manifest_path"]).is_file()
    assert Path(summary["calibration_root"]).joinpath("calibration_report.json").is_file()
