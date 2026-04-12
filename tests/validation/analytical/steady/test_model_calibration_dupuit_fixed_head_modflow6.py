"""End-to-end calibration check for the steady Dupuit fixed-head MODFLOW 6 case."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from launchers import HydroModPyLauncher
from launchers.model_calibration.launcher import ModelCalibrationLauncher
from launchers.model_calibration.runtime import (
    actualize_candidate,
    execute_candidate_run,
    select_candidate_outputs,
)
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
    outcome = execute_candidate_run(
        request=request,
        launcher_factory=HydroModPyLauncher,
        cfg=launcher.cfg,
    )
    assert outcome.status == "objective_evaluated"
    selected = select_candidate_outputs(
        cfg=launcher.cfg,
        run_state=outcome.run_state,
        session=request.session,
    )
    return float(selected["q_east"][0])


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
