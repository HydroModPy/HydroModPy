"""Same-solver twin benchmark for steady scalar K recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    ObservationNoiseSpec,
    TwinCalibrationCaseDefinition,
)
from validation_cases.shared.runtime import _merge_toml_payloads, _read_toml


CASE_DIR = (
    Path(__file__).resolve().parents[4]
    / "analytical"
    / "steady"
    / "dupuit_fixed_head_1d"
)


def build_simulation_config(path: Path, project_root: Path) -> None:
    """Write one MODFLOW 6 simulation config for the steady twin benchmark."""
    from validation_cases.shared.runtime import _dump_toml

    payload = _merge_toml_payloads(
        _read_toml(CASE_DIR / "config_common.toml"),
        _read_toml(CASE_DIR / "config_modflow6.toml"),
    )
    payload.setdefault("workspace", {})["project_root"] = str(project_root)
    payload.setdefault("simulation", {})["run_id"] = "steady_dupuit_truth"
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def build_calibration_payload(
    simulation_config_name: str,
    calibration_id: str,
    observed_values: dict[str, tuple[float, ...]],
    method_profile: CalibrationMethodProfile,
) -> dict[str, Any]:
    """Build one calibration payload for the steady scalar twin benchmark."""
    return {
        "model_calibration": {
            "simulation_config": simulation_config_name,
            "calibration_id": calibration_id,
            "disable_display": True,
            "disable_postprocess": True,
            "rerun_best_with_outputs": False,
            "persist_model_distribution": bool(method_profile.persist_model_distribution),
            "rerun_model_distribution_with_outputs": False,
            "persist_iteration_history": True,
            "persist_iteration_detail_level": "minimal",
            "persist_calibration_report": True,
            "resume_existing_session": False,
            "reuse_persisted_iterations": False,
            "parameter": [
                {
                    "name": "K_global_factor",
                    "property": "K",
                    "target": "flow.param.K.field_homogeneous.value",
                    "mode": "scale",
                    "parameterization": "global_factor",
                }
            ],
            "output": [
                {
                    "name": "q_east",
                    "variable": "outlet_discharge",
                    "source": "runtime",
                    "support": "boundary",
                    "boundary_id": "east_side",
                    "time": "all",
                    "observed_values": list(observed_values["q_east"]),
                }
            ],
            "objective_block": [
                {
                    "name": "flux",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["q_east"],
                    "normalize_cost": True,
                }
            ],
        },
        "calibration": {
            "objective_metric": "rmse",
            "global_method": method_profile.name,
        },
        "objective": {
            "transform": "identity",
        },
        "calibration_method": {
            method_profile.name: dict(method_profile.method_kwargs),
        },
        "bounds": {
            "K_global_factor": [0.8, 1.2],
        },
    }


STEADY_DUPUIT_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Same-solver twin benchmark on dupuit_fixed_head_1d with one scalar "
        "K multiplier and one outlet-discharge observable."
    ),
    truth_params={"K_global_factor": 1.0},
    bounds={"K_global_factor": (0.8, 1.2)},
    parameter_abs_tolerances={"K_global_factor": 0.06},
    output_names=("q_east",),
    method_profiles=(
        CalibrationMethodProfile(
            name="grid_search",
            method_kwargs={"n_per_dim": 9},
            persist_model_distribution=False,
        ),
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"n_samples": 16, "seed": 7},
            persist_model_distribution=True,
        ),
        CalibrationMethodProfile(
            name="simplex",
            method_kwargs={"max_iter": 24, "xtol": 1.0e-8, "ftol": 1.0e-8},
            persist_model_distribution=False,
        ),
    ),
    fast=True,
    build_simulation_config=build_simulation_config,
    build_calibration_payload=build_calibration_payload,
)


STEADY_DUPUIT_NOISY_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_noisy_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Same-solver noisy twin benchmark on dupuit_fixed_head_1d with one "
        "scalar K multiplier, one outlet-discharge observable, and repeated "
        "random-search seeds."
    ),
    truth_params={"K_global_factor": 1.0},
    bounds={"K_global_factor": (0.8, 1.2)},
    parameter_abs_tolerances={"K_global_factor": 0.06},
    output_names=("q_east",),
    method_profiles=(
        CalibrationMethodProfile(
            name="grid_search",
            method_kwargs={"n_per_dim": 9},
            persist_model_distribution=False,
        ),
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"n_samples": 16},
            persist_model_distribution=True,
            repeat_seeds=(7, 11, 19),
        ),
        CalibrationMethodProfile(
            name="simplex",
            method_kwargs={"max_iter": 24, "xtol": 1.0e-8, "ftol": 1.0e-8},
            persist_model_distribution=False,
        ),
    ),
    fast=False,
    observation_noise=ObservationNoiseSpec(
        relative_sigma_by_output={"q_east": 0.01},
        seed=21,
    ),
    build_simulation_config=build_simulation_config,
    build_calibration_payload=build_calibration_payload,
)
