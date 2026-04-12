"""Same-solver twin benchmark for transient K+Sy recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    TwinCalibrationCaseDefinition,
)
from validation_cases.shared.runtime import _merge_toml_payloads, _read_toml


CASE_DIR = (
    Path(__file__).resolve().parents[4]
    / "analytical"
    / "transient"
    / "linearized_unconfined_recharge_step_1d"
)


def build_simulation_config(path: Path, project_root: Path) -> None:
    """Write one MODFLOW 6 simulation config for the transient twin benchmark."""
    from validation_cases.shared.runtime import _dump_toml

    payload = _merge_toml_payloads(
        _read_toml(CASE_DIR / "config_modflownwt.toml"),
        _read_toml(CASE_DIR / "config_modflow6.toml"),
    )
    payload.setdefault("workspace", {})["project_root"] = str(project_root)
    payload.setdefault("simulation", {})["run_id"] = "transient_lu_truth"
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def build_calibration_payload(
    simulation_config_name: str,
    calibration_id: str,
    observed_values: dict[str, tuple[float, ...]],
    method_profile: CalibrationMethodProfile,
) -> dict[str, Any]:
    """Build one calibration payload for the transient multiobservable twin benchmark."""
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
                    "name": "head_mid",
                    "variable": "watertable_elevation",
                    "source": "runtime",
                    "support": "point",
                    "x": 50.0,
                    "y": 5.0,
                    "time": "all",
                    "observed_values": list(observed_values["head_mid"]),
                },
                {
                    "name": "q_east",
                    "variable": "outlet_discharge",
                    "source": "runtime",
                    "support": "boundary",
                    "boundary_id": "east_side",
                    "time": "all",
                    "observed_values": list(observed_values["q_east"]),
                },
            ],
            "objective_block": [
                {
                    "name": "heads",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["head_mid"],
                    "normalize_cost": True,
                },
                {
                    "name": "flux",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["q_east"],
                    "normalize_cost": True,
                },
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
            "K_global_factor": [0.95, 1.05],
            "Sy_global": [0.06, 0.14],
        },
    }


TRANSIENT_RECHARGE_STEP_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_linearized_recharge_step_modflow6",
    solver_name="modflow6",
    regime="transient",
    description=(
        "Same-solver twin benchmark on linearized_unconfined_recharge_step_1d "
        "with K+Sy and multiobservable head/flux blocks."
    ),
    truth_params={"K_global_factor": 1.0, "Sy_global": 0.10},
    bounds={
        "K_global_factor": (0.95, 1.05),
        "Sy_global": (0.06, 0.14),
    },
    parameter_abs_tolerances={
        "K_global_factor": 0.03,
        "Sy_global": 0.03,
    },
    output_names=("head_mid", "q_east"),
    method_profiles=(
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"n_samples": 10, "seed": 11},
            persist_model_distribution=True,
        ),
        CalibrationMethodProfile(
            name="simplex",
            method_kwargs={"max_iter": 10, "xtol": 1.0e-6, "ftol": 1.0e-6},
            persist_model_distribution=False,
        ),
    ),
    fast=False,
    build_simulation_config=build_simulation_config,
    build_calibration_payload=build_calibration_payload,
)

